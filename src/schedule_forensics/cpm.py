"""Critical Path Method engine -- forward + backward pass (trust-root, LAW 2).

The internal time axis is INTEGER WORKING MINUTES, measured as an offset from
``Schedule.project_start``. An integer working-minute axis makes the arithmetic
exact and hand-verifiable, and removes the end-of-day / start-of-next-day
boundary class of bugs by construction.

Scope of this slice (documented, not silently limited -- see PHASE-COMPLETE-1.md):
  * Link types: all four (FS/SS/FF/SF) with lag/lead, in working minutes.
  * Date constraints honored under MS Project's "honor constraint dates" mode:
    SNET / FNET (forward floors), SNLT / FNLT (backward caps), and task
    ``deadline`` (a backward cap that can drive negative float). A conflict
    surfaces as negative total float rather than a rescheduled date.
  * NOT yet honored -- the engine RAISES ``CPMError`` rather than emit a
    silently-wrong schedule (LAW 2): ALAP, Must-Start-On (MSO), Must-Finish-On
    (MFO). Their pin semantics interact subtly with float and require live
    MS Project validation (unavailable on Linux -- docs/HAZARDS.md).
  * Total float MAY be negative (imposed finish, or a violated cap/deadline).

Critical-path definition: ``total_float <= 0`` (matches MS Project once negative
float exists). Cited in docs/REFERENCES.md.

datetime->offset mapping: constraint/deadline datetimes are converted to working
minutes at working-day granularity plus a clamped intraday term. The precise
"honor constraint dates" intraday/edge behavior is a defined model pending live
MS Project validation (docs/HAZARDS.md, H-CONSTRAINT-DATETIME).
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from dataclasses import dataclass

from schedule_forensics.schemas import (
    Calendar,
    ConstraintType,
    RelationType,
    Schedule,
    Task,
)

_DEFERRED_CONSTRAINTS = frozenset({ConstraintType.ALAP, ConstraintType.MSO, ConstraintType.MFO})
_DATE_CONSTRAINTS = frozenset(
    {ConstraintType.SNET, ConstraintType.FNET, ConstraintType.SNLT, ConstraintType.FNLT}
)


class CPMError(ValueError):
    """Raised when the network cannot be scheduled -- a logic cycle, or a date
    constraint that is not yet honored (refusing rather than emitting a
    silently-wrong schedule)."""


@dataclass(frozen=True)
class TaskTiming:
    """Computed schedule for one task, in working-minute offsets from start."""

    unique_id: int
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    total_float: int
    free_float: int
    is_critical: bool


@dataclass(frozen=True)
class CPMResult:
    """The full forward/backward-pass result for a schedule."""

    timings: dict[int, TaskTiming]
    project_finish: int  # working-minute offset of the network's latest early finish
    critical_path: tuple[int, ...]  # unique_ids with total_float <= 0, in topo order


# An edge as carried through the engine: (predecessor_id, successor_id, type, lag).
_Edge = tuple[int, int, RelationType, int]
# A neighbour reference on one side of a link: (other_id, type, lag).
_Link = tuple[int, RelationType, int]


def _scheduled_tasks(schedule: Schedule) -> list[Task]:
    # Summary tasks are date rollups, not real activities -- excluded from the network.
    return [t for t in schedule.tasks if not t.is_summary]


def _es_lower_bound(rel: RelationType, es_p: int, ef_p: int, lag: int, dur_s: int) -> int:
    """Lower bound a predecessor link imposes on the successor's early start."""
    if rel is RelationType.FS:
        return ef_p + lag
    if rel is RelationType.SS:
        return es_p + lag
    if rel is RelationType.FF:
        return ef_p + lag - dur_s
    return es_p + lag - dur_s  # SF


def _lf_upper_bound(rel: RelationType, ls_s: int, lf_s: int, lag: int, dur_p: int) -> int:
    """Upper bound a successor link imposes on the predecessor's late finish."""
    if rel is RelationType.FS:
        return ls_s - lag
    if rel is RelationType.SS:
        return ls_s - lag + dur_p
    if rel is RelationType.FF:
        return lf_s - lag
    return lf_s - lag + dur_p  # SF


def _link_slack(rel: RelationType, es_p: int, ef_p: int, es_s: int, ef_s: int, lag: int) -> int:
    """Relationship slack for free-float: how far P may slip before this link binds.

    Reduces to the standard FS free float. For SS/FF/SF this is the slack measured
    at the link's governing event (reference tools vary on non-FS free float; total
    float -- the primary forensic signal -- is exact for every type)."""
    if rel is RelationType.FS:
        return es_s - (ef_p + lag)
    if rel is RelationType.SS:
        return es_s - (es_p + lag)
    if rel is RelationType.FF:
        return ef_s - (ef_p + lag)
    return ef_s - (es_p + lag)  # SF


def _count_working_days(calendar: Calendar, d0: dt.date, d1: dt.date) -> int:
    """Number of working days in the half-open range [d0, d1) (requires d0 <= d1)."""
    count = 0
    cur = d0
    while cur < d1:
        if cur.weekday() in calendar.work_weekdays and cur not in calendar.holidays:
            count += 1
        cur += dt.timedelta(days=1)
    return count


def datetime_to_offset(start: dt.datetime, target: dt.datetime, calendar: Calendar) -> int:
    """Signed working-minute offset of ``target`` from ``start``.

    ``start`` is assumed to sit at a working-day start. The date contributes whole
    working days; the intraday term is ``(target_time - start_time)`` clamped to
    ``[0, working_minutes_per_day]``. A target on a non-working day contributes no
    intraday minutes. See the module docstring (H-CONSTRAINT-DATETIME)."""
    per_day = calendar.working_minutes_per_day
    start_tod = start.hour * 60 + start.minute
    target_tod = target.hour * 60 + target.minute
    on_working_day = (
        target.date().weekday() in calendar.work_weekdays and target.date() not in calendar.holidays
    )
    intraday = min(max(target_tod - start_tod, 0), per_day) if on_working_day else 0
    if target.date() >= start.date():
        return _count_working_days(calendar, start.date(), target.date()) * per_day + intraday
    return -_count_working_days(calendar, target.date(), start.date()) * per_day + intraday


def _topo_order(task_ids: list[int], edges: list[tuple[int, int]]) -> list[int]:
    """Kahn topological sort over precedence edges (pred -> succ). Raises on a cycle."""
    successors: dict[int, list[int]] = {tid: [] for tid in task_ids}
    indegree: dict[int, int] = dict.fromkeys(task_ids, 0)
    for pred, succ in edges:
        successors[pred].append(succ)
        indegree[succ] += 1
    queue: deque[int] = deque(sorted(tid for tid in task_ids if indegree[tid] == 0))
    order: list[int] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        ready: list[int] = []
        for succ in successors[node]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                ready.append(succ)
        queue.extend(sorted(ready))  # deterministic ordering
    if len(order) != len(task_ids):
        raise CPMError("schedule logic contains a cycle; cannot compute CPM")
    return order


def _constraint_bounds(
    schedule: Schedule, tasks: list[Task], duration: dict[int, int]
) -> tuple[dict[int, int], dict[int, int]]:
    """Return (es_floor, lf_cap) in working-minute offsets from date constraints + deadlines.

    Raises ``CPMError`` for deferred constraints (ALAP/MSO/MFO) or a date
    constraint missing its ``constraint_date``."""
    deferred = [t.unique_id for t in tasks if t.constraint_type in _DEFERRED_CONSTRAINTS]
    if deferred:
        raise CPMError(
            "ALAP / Must-Start-On / Must-Finish-On constraints are not yet honored "
            f"(deferred; see docs/HAZARDS.md); affected task UniqueIDs: {deferred}"
        )

    es_floor: dict[int, int] = {}
    lf_cap: dict[int, int] = {}
    for task in tasks:
        tid = task.unique_id
        if task.constraint_type in _DATE_CONSTRAINTS:
            if task.constraint_date is None:
                raise CPMError(
                    f"task {tid} has constraint {task.constraint_type} but no constraint_date"
                )
            off = datetime_to_offset(
                schedule.project_start, task.constraint_date, schedule.calendar
            )
            if task.constraint_type is ConstraintType.SNET:
                es_floor[tid] = off
            elif task.constraint_type is ConstraintType.FNET:
                es_floor[tid] = off - duration[tid]
            elif task.constraint_type is ConstraintType.SNLT:
                lf_cap[tid] = off + duration[tid]
            else:  # FNLT
                lf_cap[tid] = off
        if task.deadline is not None:
            d_off = datetime_to_offset(schedule.project_start, task.deadline, schedule.calendar)
            lf_cap[tid] = min(lf_cap.get(tid, d_off), d_off)
    return es_floor, lf_cap


def compute_cpm(schedule: Schedule, required_finish_offset: int | None = None) -> CPMResult:
    """Run the forward and backward passes and return per-task timings.

    ``required_finish_offset`` (working minutes) imposes an earlier project finish
    for the backward pass; when it is earlier than the network's own early finish,
    the driving chain shows negative total float.

    Raises ``CPMError`` on a logic cycle or an unsupported constraint (see the
    module docstring).
    """
    tasks = _scheduled_tasks(schedule)
    duration: dict[int, int] = {t.unique_id: t.duration_minutes for t in tasks}
    es_floor, lf_cap = _constraint_bounds(schedule, tasks, duration)

    task_ids = [t.unique_id for t in tasks]
    id_set = set(task_ids)
    edges: list[_Edge] = [
        (r.predecessor_id, r.successor_id, r.type, r.lag_minutes)
        for r in schedule.relations
        if r.predecessor_id in id_set and r.successor_id in id_set
    ]
    order = _topo_order(task_ids, [(pred, succ) for pred, succ, _rel, _lag in edges])

    preds: dict[int, list[_Link]] = {tid: [] for tid in task_ids}
    succs: dict[int, list[_Link]] = {tid: [] for tid in task_ids}
    for pred, succ, rel, lag in edges:
        preds[succ].append((pred, rel, lag))
        succs[pred].append((succ, rel, lag))

    # ---- forward pass (ES floored at 0 == project start, and by SNET/FNET) ----
    early_start: dict[int, int] = {}
    early_finish: dict[int, int] = {}
    for tid in order:
        dur_s = duration[tid]
        bounds = [
            _es_lower_bound(rel, early_start[p], early_finish[p], lag, dur_s)
            for p, rel, lag in preds[tid]
        ]
        if tid in es_floor:
            bounds.append(es_floor[tid])
        es = max([0, *bounds])
        early_start[tid] = es
        early_finish[tid] = es + dur_s

    network_finish = max(early_finish.values(), default=0)
    backward_target = (
        required_finish_offset if required_finish_offset is not None else network_finish
    )

    # ---- backward pass (LF capped at the backward target, and by SNLT/FNLT/deadline) ----
    late_finish: dict[int, int] = {}
    late_start: dict[int, int] = {}
    for tid in reversed(order):
        dur_p = duration[tid]
        bounds = [
            _lf_upper_bound(rel, late_start[s], late_finish[s], lag, dur_p)
            for s, rel, lag in succs[tid]
        ]
        if tid in lf_cap:
            bounds.append(lf_cap[tid])
        lf = min([backward_target, *bounds])
        late_finish[tid] = lf
        late_start[tid] = lf - dur_p

    timings: dict[int, TaskTiming] = {}
    for tid in task_ids:
        total = late_start[tid] - early_start[tid]
        if succs[tid]:
            free = min(
                _link_slack(
                    rel,
                    early_start[tid],
                    early_finish[tid],
                    early_start[s],
                    early_finish[s],
                    lag,
                )
                for s, rel, lag in succs[tid]
            )
        else:
            free = backward_target - early_finish[tid]
        timings[tid] = TaskTiming(
            unique_id=tid,
            early_start=early_start[tid],
            early_finish=early_finish[tid],
            late_start=late_start[tid],
            late_finish=late_finish[tid],
            total_float=total,
            free_float=free,
            is_critical=total <= 0,
        )

    critical_path = tuple(tid for tid in order if timings[tid].is_critical)
    return CPMResult(timings=timings, project_finish=network_finish, critical_path=critical_path)


def _next_working_day(day: dt.datetime, calendar: Calendar) -> dt.datetime:
    nxt = day + dt.timedelta(days=1)
    while nxt.date().weekday() not in calendar.work_weekdays or nxt.date() in calendar.holidays:
        nxt += dt.timedelta(days=1)
    return nxt


def offset_to_datetime(start: dt.datetime, minutes: int, calendar: Calendar) -> dt.datetime:
    """Convert a non-negative working-minute offset to a wall-clock datetime.

    ``start`` is assumed to sit at the beginning of a working day. Each working
    weekday contributes ``calendar.working_minutes_per_day`` contiguous minutes;
    weekends and holidays are skipped.
    """
    if minutes < 0:
        raise ValueError("offset_to_datetime: minutes must be >= 0")
    per_day = calendar.working_minutes_per_day
    day = start
    while day.date().weekday() not in calendar.work_weekdays or day.date() in calendar.holidays:
        day = _next_working_day(day, calendar)
    remaining = minutes
    while remaining > 0:
        if remaining <= per_day:
            return day + dt.timedelta(minutes=remaining)
        remaining -= per_day
        day = _next_working_day(day, calendar)
    return day
