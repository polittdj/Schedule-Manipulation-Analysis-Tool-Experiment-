"""DCMA 14-Point Assessment -- the STRUCTURAL checks (Metrics 1-8).

This module implements the eight DCMA-14 checks that depend only on schedule
*structure* (logic, lags/leads, relationship types, constraints) plus the CPM
total-float field -- i.e. the checks that need no progress/tracking data. The
six progress-dependent checks (Invalid Dates, Resources, Missed Tasks, Critical
Path Test, CPLI, BEI) live in a separate module by design (one module per
dispatch, CLAUDE.md commandment 4).

The eight checks here, with their canonical DCMA thresholds:

  * DCMA-01 Missing Logic           -- <= 5% of tasks lack a predecessor OR successor
  * DCMA-02 Leads (negative lag)    -- == 0 relationships with a negative lag
  * DCMA-03 Lags                    -- <= 5% of relationships carry a positive lag
  * DCMA-04 Relationship Types      -- >= 90% of relationships are Finish-to-Start
  * DCMA-05 Hard Constraints        -- <= 5% of tasks carry a hard date constraint
  * DCMA-06 High Float              -- <= 5% of incomplete tasks have total float > 44d
  * DCMA-07 Negative Float          -- == 0% of tasks have negative total float
  * DCMA-08 High Duration           -- <= 5% of incomplete tasks have duration > 44d

Source / parity honesty (LAW 2): these checks and threshold *values* are the
canonical DCMA 14-Point Assessment numbers (REFERENCES.md keys ``DCMA-EDWARDS``
/ ``DCMA-WINTER``). The threshold values are well-known and canonical, but the
exact page anchors are **source-pending** until those documents land in
``docs/sources/`` -- every ``Threshold.source`` below says so explicitly rather
than inventing a page number (H-FICTIONAL-RULE). None of these eight is a
tool-original extension; they are reference-tool checks and are NOT flagged
``is_extension``.

Single source of truth (H-DRIFT-2): each threshold is a module-level
:class:`~schedule_forensics.metrics_common.Threshold` constant; the corresponding
check reads that constant and nothing else. A parametrized test pins value,
direction, and a non-empty cited source for every metric id.

Units: the working-minute axis matches :mod:`schedule_forensics.cpm` -- 480
working minutes == one 8-hour day, so the DCMA "44 working days" threshold is
``44 * 480 == 21120`` working minutes (``_FORTY_FOUR_DAYS_MIN`` below).

Scope conventions (CLAUDE.md): every check operates on NON-SUMMARY tasks only
(summaries are date rollups, absent from :class:`~schedule_forensics.cpm.CPMResult`
timings). "Incomplete" means ``percent_complete < 100``. A check whose
denominator would be zero (no relationships for M2/M3/M4, no tasks for the
others) returns SKIPPED with a reason -- it never divides by zero and never
reports a fabricated ``0`` or ``100`` (H-DRIFT-1).
"""

from __future__ import annotations

from schedule_forensics.cpm import CPMError, CPMResult, compute_cpm
from schedule_forensics.metrics_common import (
    Direction,
    MetricResult,
    Offender,
    Threshold,
    evaluate,
    skipped,
)
from schedule_forensics.schemas import ConstraintType, RelationType, Schedule, Task

# --- working-minute axis (single source of truth for the day conversion) ---
_WORKING_MINUTES_PER_DAY = 480
# DCMA "44 working days" high-float / high-duration threshold, in working minutes.
_FORTY_FOUR_DAYS_MIN = 44 * _WORKING_MINUTES_PER_DAY  # 21120

# Hard date constraints per DCMA: a two-way (MSO/MFO) or one-way "no later than"
# (SNLT/FNLT) pin that can stop the network from logic-rescheduling. SNET/FNET
# are SOFT ("no earlier than"); ASAP/ALAP impose no fixed date. (DCMA-EDWARDS M5.)
_HARD_CONSTRAINTS = frozenset(
    {ConstraintType.MSO, ConstraintType.MFO, ConstraintType.SNLT, ConstraintType.FNLT}
)

# --- thresholds: defined ONCE here, each cited; checks read these constants ---
# The values are the canonical DCMA 14-Point numbers; page anchors are pending
# (the DCMA-EDWARDS / DCMA-WINTER PDFs are not yet in docs/sources/).
_SRC_M1 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M1 (Missing Logic); page-anchor source-pending"
_SRC_M2 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M2 (Leads); page-anchor source-pending"
_SRC_M3 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M3 (Lags); page-anchor source-pending"
_SRC_M4 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M4 (Relationship Types); page-anchor source-pending"
_SRC_M5 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M5 (Hard Constraints); page-anchor source-pending"
_SRC_M6 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M6 (High Float); page-anchor source-pending"
_SRC_M7 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M7 (Negative Float); page-anchor source-pending"
_SRC_M8 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M8 (High Duration); page-anchor source-pending"

THRESHOLD_MISSING_LOGIC = Threshold(value=5.0, direction=Direction.LE, source=_SRC_M1)
THRESHOLD_LEADS = Threshold(value=0.0, direction=Direction.EQ, source=_SRC_M2)
THRESHOLD_LAGS = Threshold(value=5.0, direction=Direction.LE, source=_SRC_M3)
THRESHOLD_RELATIONSHIP_TYPES = Threshold(value=90.0, direction=Direction.GE, source=_SRC_M4)
THRESHOLD_HARD_CONSTRAINTS = Threshold(value=5.0, direction=Direction.LE, source=_SRC_M5)
THRESHOLD_HIGH_FLOAT = Threshold(value=5.0, direction=Direction.LE, source=_SRC_M6)
THRESHOLD_NEGATIVE_FLOAT = Threshold(value=0.0, direction=Direction.EQ, source=_SRC_M7)
THRESHOLD_HIGH_DURATION = Threshold(value=5.0, direction=Direction.LE, source=_SRC_M8)


def _non_summary(schedule: Schedule) -> list[Task]:
    """Real activities only -- summaries are rollups (absent from CPM timings)."""
    return [t for t in schedule.tasks if not t.is_summary]


def _is_incomplete(task: Task) -> bool:
    """DCMA "incomplete" task: not yet 100% complete (default 0.0 => incomplete)."""
    return task.percent_complete < 100.0


def _pct(count: int, total: int) -> float:
    """Percentage in 0..100 as a float. Caller guarantees ``total > 0``."""
    return 100.0 * count / total


def check_missing_logic(schedule: Schedule) -> MetricResult:
    """DCMA-01: % of non-summary tasks lacking a predecessor OR a successor link.

    A task "has logic" on a side if it appears (on that side) in at least one
    relation whose *other* endpoint is also a non-summary task; links touching a
    summary are ignored, since summaries are not real activities. A task missing
    either side is an offender and is counted ONCE in the numerator even if it is
    missing both sides (it then yields two ``Offender`` rows -- one per side).

    Bookend note: a project's true start milestone may legitimately have no
    predecessor, and its true finish milestone no successor (a documented
    modeling choice). DCMA counts every dangling task by default; this check does
    too (it does not auto-exempt bookends). A caller wanting the bookend-exempt
    variant filters the offenders. (DCMA-EDWARDS M1.)
    """
    tasks = _non_summary(schedule)
    if not tasks:
        return skipped("DCMA-01", "Missing Logic", "schedule has no non-summary tasks")

    real_ids = {t.unique_id for t in tasks}
    has_predecessor: set[int] = set()  # task ids that appear as a successor
    has_successor: set[int] = set()  # task ids that appear as a predecessor
    for rel in schedule.relations:
        if rel.predecessor_id in real_ids and rel.successor_id in real_ids:
            has_successor.add(rel.predecessor_id)
            has_predecessor.add(rel.successor_id)

    offenders: list[Offender] = []
    dangling_ids: set[int] = set()
    for task in tasks:
        tid = task.unique_id
        if tid not in has_predecessor:
            offenders.append(
                Offender(unique_id=tid, kind="missing_predecessor", value=1.0, detail=task.name)
            )
            dangling_ids.add(tid)
        if tid not in has_successor:
            offenders.append(
                Offender(unique_id=tid, kind="missing_successor", value=1.0, detail=task.name)
            )
            dangling_ids.add(tid)

    measured = _pct(len(dangling_ids), len(tasks))
    detail = (
        f"{len(dangling_ids)} of {len(tasks)} non-summary tasks lack a predecessor or successor"
    )
    return evaluate(
        "DCMA-01",
        "Missing Logic",
        measured,
        THRESHOLD_MISSING_LOGIC,
        offenders=tuple(offenders),
        detail=detail,
    )


def check_leads(schedule: Schedule) -> MetricResult:
    """DCMA-02: COUNT of relationships with a negative lag (a "lead").

    DCMA requires zero leads (a lead pulls a successor earlier than its logic
    allows and is a classic manipulation signal). ``measured`` is the count of
    offending relationships, not a percentage; the threshold is ``== 0``. Each
    offender keys on the successor's ``unique_id`` with ``value`` = the (negative)
    lag in working minutes. (DCMA-EDWARDS M2.)
    """
    relations = schedule.relations
    if not relations:
        return skipped("DCMA-02", "Leads", "schedule has no relationships")

    offenders = tuple(
        Offender(
            unique_id=rel.successor_id,
            kind="lead_minutes",
            value=float(rel.lag_minutes),
            detail=f"{rel.predecessor_id}->{rel.successor_id} {rel.type.value}",
        )
        for rel in relations
        if rel.lag_minutes < 0
    )
    measured = float(len(offenders))
    detail = f"{len(offenders)} of {len(relations)} relationships use a lead (negative lag)"
    return evaluate(
        "DCMA-02", "Leads", measured, THRESHOLD_LEADS, offenders=offenders, detail=detail
    )


def check_lags(schedule: Schedule) -> MetricResult:
    """DCMA-03: % of relationships that carry a positive lag.

    A lag (positive offset) inserts delay into logic without a modeled activity;
    DCMA allows it on at most 5% of links. Offenders key on the successor's
    ``unique_id`` with ``value`` = the (positive) lag in working minutes.
    (DCMA-EDWARDS M3.)
    """
    relations = schedule.relations
    if not relations:
        return skipped("DCMA-03", "Lags", "schedule has no relationships")

    offenders = tuple(
        Offender(
            unique_id=rel.successor_id,
            kind="lag_minutes",
            value=float(rel.lag_minutes),
            detail=f"{rel.predecessor_id}->{rel.successor_id} {rel.type.value}",
        )
        for rel in relations
        if rel.lag_minutes > 0
    )
    measured = _pct(len(offenders), len(relations))
    detail = f"{len(offenders)} of {len(relations)} relationships carry a positive lag"
    return evaluate("DCMA-03", "Lags", measured, THRESHOLD_LAGS, offenders=offenders, detail=detail)


def check_relationship_types(schedule: Schedule) -> MetricResult:
    """DCMA-04: % of relationships that are Finish-to-Start (FS).

    DCMA wants the schedule dominated by FS logic (>= 90%); SS/FF/SF should be the
    exception. ``measured`` is the FS share as a percentage. Offenders are the
    NON-FS relationships (keyed on the successor's ``unique_id``, ``value`` = the
    lag), since those are the links pulling the metric down. (DCMA-EDWARDS M4.)
    """
    relations = schedule.relations
    if not relations:
        return skipped("DCMA-04", "Relationship Types", "schedule has no relationships")

    fs_count = sum(1 for rel in relations if rel.type is RelationType.FS)
    offenders = tuple(
        Offender(
            unique_id=rel.successor_id,
            kind="non_fs_relationship",
            value=float(rel.lag_minutes),
            detail=f"{rel.predecessor_id}->{rel.successor_id} {rel.type.value}",
        )
        for rel in relations
        if rel.type is not RelationType.FS
    )
    measured = _pct(fs_count, len(relations))
    detail = f"{fs_count} of {len(relations)} relationships are Finish-to-Start"
    return evaluate(
        "DCMA-04",
        "Relationship Types",
        measured,
        THRESHOLD_RELATIONSHIP_TYPES,
        offenders=offenders,
        detail=detail,
    )


def check_hard_constraints(schedule: Schedule) -> MetricResult:
    """DCMA-05: % of non-summary tasks carrying a HARD date constraint.

    Hard = ``{MSO, MFO, SNLT, FNLT}`` (see ``_HARD_CONSTRAINTS``). SNET/FNET are
    soft ("no earlier than"); ASAP/ALAP impose no fixed date. Hard constraints
    override logic and are a manipulation signal; DCMA allows them on at most 5%
    of tasks. This check needs no CPM (it reads ``constraint_type`` directly), so
    it runs even when MSO/MFO would make the CPM defer. (DCMA-EDWARDS M5.)
    """
    tasks = _non_summary(schedule)
    if not tasks:
        return skipped("DCMA-05", "Hard Constraints", "schedule has no non-summary tasks")

    offenders = tuple(
        Offender(
            unique_id=task.unique_id,
            kind="hard_constraint",
            value=1.0,
            detail=f"{task.constraint_type.value}",
        )
        for task in tasks
        if task.constraint_type in _HARD_CONSTRAINTS
    )
    measured = _pct(len(offenders), len(tasks))
    detail = f"{len(offenders)} of {len(tasks)} non-summary tasks carry a hard constraint"
    return evaluate(
        "DCMA-05",
        "Hard Constraints",
        measured,
        THRESHOLD_HARD_CONSTRAINTS,
        offenders=offenders,
        detail=detail,
    )


def check_high_float(schedule: Schedule, result: CPMResult) -> MetricResult:
    """DCMA-06: % of INCOMPLETE non-summary tasks with total float > 44 working days.

    Excessive total float (> ``_FORTY_FOUR_DAYS_MIN`` == 21120 working minutes)
    suggests missing logic or an under-constrained network. The denominator is the
    incomplete non-summary tasks present in the CPM result; completed tasks are
    excluded. Offenders key on ``unique_id`` with ``value`` = the float in working
    minutes. Requires a CPM result (see :func:`run_structural_checks` for the
    skip-on-CPMError handling). (DCMA-EDWARDS M6.)
    """
    incomplete = [t for t in _non_summary(schedule) if _is_incomplete(t)]
    timed = [t for t in incomplete if t.unique_id in result.timings]
    if not timed:
        return skipped("DCMA-06", "High Float", "no incomplete non-summary tasks with CPM timings")

    offenders = tuple(
        Offender(
            unique_id=t.unique_id,
            kind="total_float_minutes",
            value=float(result.timings[t.unique_id].total_float),
            detail=t.name,
        )
        for t in timed
        if result.timings[t.unique_id].total_float > _FORTY_FOUR_DAYS_MIN
    )
    measured = _pct(len(offenders), len(timed))
    detail = (
        f"{len(offenders)} of {len(timed)} incomplete tasks have total float > "
        f"44 working days ({_FORTY_FOUR_DAYS_MIN} min)"
    )
    return evaluate(
        "DCMA-06", "High Float", measured, THRESHOLD_HIGH_FLOAT, offenders=offenders, detail=detail
    )


def check_negative_float(schedule: Schedule, result: CPMResult) -> MetricResult:
    """DCMA-07: % of non-summary tasks with negative total float.

    Negative total float means the network cannot meet an imposed/constraint date
    on the current logic -- DCMA requires zero such tasks. The denominator is all
    non-summary tasks present in the CPM result. Offenders key on ``unique_id``
    with ``value`` = the (negative) float in working minutes. Requires a CPM
    result (skip-on-CPMError handled by :func:`run_structural_checks`).
    (DCMA-EDWARDS M7.)
    """
    timed = [t for t in _non_summary(schedule) if t.unique_id in result.timings]
    if not timed:
        return skipped("DCMA-07", "Negative Float", "no non-summary tasks with CPM timings")

    offenders = tuple(
        Offender(
            unique_id=t.unique_id,
            kind="total_float_minutes",
            value=float(result.timings[t.unique_id].total_float),
            detail=t.name,
        )
        for t in timed
        if result.timings[t.unique_id].total_float < 0
    )
    measured = _pct(len(offenders), len(timed))
    detail = f"{len(offenders)} of {len(timed)} non-summary tasks have negative total float"
    return evaluate(
        "DCMA-07",
        "Negative Float",
        measured,
        THRESHOLD_NEGATIVE_FLOAT,
        offenders=offenders,
        detail=detail,
    )


def check_high_duration(schedule: Schedule) -> MetricResult:
    """DCMA-08: % of INCOMPLETE non-summary tasks with duration > 44 working days.

    A baseline-duration task longer than ``_FORTY_FOUR_DAYS_MIN`` (21120 working
    minutes) is too coarse to track and should be broken down. The denominator is
    the incomplete non-summary tasks; offenders key on ``unique_id`` with
    ``value`` = the duration in working minutes. Needs no CPM. (DCMA-EDWARDS M8.)
    """
    incomplete = [t for t in _non_summary(schedule) if _is_incomplete(t)]
    if not incomplete:
        return skipped("DCMA-08", "High Duration", "no incomplete non-summary tasks")

    offenders = tuple(
        Offender(
            unique_id=t.unique_id,
            kind="duration_minutes",
            value=float(t.duration_minutes),
            detail=t.name,
        )
        for t in incomplete
        if t.duration_minutes > _FORTY_FOUR_DAYS_MIN
    )
    measured = _pct(len(offenders), len(incomplete))
    detail = (
        f"{len(offenders)} of {len(incomplete)} incomplete tasks have duration > "
        f"44 working days ({_FORTY_FOUR_DAYS_MIN} min)"
    )
    return evaluate(
        "DCMA-08",
        "High Duration",
        measured,
        THRESHOLD_HIGH_DURATION,
        offenders=offenders,
        detail=detail,
    )


def run_structural_checks(
    schedule: Schedule, result: CPMResult | None = None
) -> tuple[MetricResult, ...]:
    """Run all eight structural DCMA-14 checks, returned in id order DCMA-01..08.

    The CPM is computed once (reusing ``result`` if supplied). If the CPM cannot
    be computed -- a logic cycle, or a deferred constraint (ALAP/MSO/MFO) -- only
    the two float-dependent checks (DCMA-06 High Float, DCMA-07 Negative Float)
    become SKIPPED with the CPM's error message as the reason; the six
    structure-only checks still run. The CPM error is never swallowed silently:
    its message is surfaced in the skip reason.
    """
    cpm: CPMResult | None = result
    cpm_error: str | None = None
    if cpm is None:
        try:
            cpm = compute_cpm(schedule)
        except CPMError as exc:
            cpm_error = str(exc)

    if cpm is not None:
        high_float = check_high_float(schedule, cpm)
        negative_float = check_negative_float(schedule, cpm)
    else:
        reason = f"CPM unavailable: {cpm_error}"
        high_float = skipped("DCMA-06", "High Float", reason)
        negative_float = skipped("DCMA-07", "Negative Float", reason)

    return (
        check_missing_logic(schedule),
        check_leads(schedule),
        check_lags(schedule),
        check_relationship_types(schedule),
        check_hard_constraints(schedule),
        high_float,
        negative_float,
        check_high_duration(schedule),
    )
