"""Objective version-to-version deltas (the comparative *facts*, not a verdict).

This module answers the forensic question "what changed, factually, between two
consecutive status updates of the same project?" Every value it emits is an
objective measured delta -- a difference of two numbers the frozen CPM engine
already computed, or a set difference of logic the schema already holds. It
applies NO threshold, makes NO judgement, and assigns NO score. (Burn-rate
classification lives elsewhere and IS labeled a tool-original extension; see
:mod:`schedule_forensics.float_analysis`.)

Because these are objective facts -- not a capability beyond what reference
tools report -- the results are NOT flagged ``is_extension``. The comparative
frame itself (compare the SAME project across absolute ``status_date`` values,
matching tasks by ``UniqueID`` only) is the Acumen/SSI ``ProjectTimeNow`` /
``ProjectPreviousTimeNow`` pattern (docs/REFERENCES.md keys: ``ACUMEN``;
"Comparative version ordering"; cited in practice, page-anchor source-pending).
The deltas themselves are arithmetic and need no separate threshold source.

Identity + ordering are delegated to the trust-root spine, never re-implemented
(Commandment 3, LAW 2):

* version ordering by absolute ``status_date`` -> ``version_matcher.order_versions``
* matched/added/deleted UniqueIDs per pair -> ``version_matcher.diff_versions``
* per-version timings (early start/finish, total float) -> ``cpm.compute_cpm``

Units: ``duration_delta_minutes``, ``total_float_delta_minutes``,
``start_shift_minutes`` and ``finish_shift_minutes`` are INTEGER WORKING-MINUTE
quantities on the same axis as :mod:`schedule_forensics.cpm` (480 working
minutes == one 8-hour day). A positive ``*_shift`` means the task moved later;
a positive ``total_float_delta`` means float was gained.

Criticality semantics match the frozen CPM engine and MS Project: a task is
critical iff ``total_float <= 0`` (docs/REFERENCES.md, "Critical path"). Thus:

* ``became_critical`` -- previous total float was strictly positive AND current
  total float is ``<= 0`` (the task crossed onto the critical path).
* ``recovered`` -- previous total float was ``<= 0`` AND current total float is
  strictly positive (the task came off the critical path).

These two flags are mutually exclusive and never both true for one task.

Scope note (documented, not silently limited): a ``TaskDelta`` is emitted only
for a matched task that is a *scheduled activity in both versions* -- present in
both versions' ``CPMResult.timings``. Summary tasks are date rollups, excluded
from the CPM network (``cpm._scheduled_tasks``) and absent from ``timings``; a
task that is a summary in either version has no CPM-derived early dates or float
and is therefore omitted from :attr:`VersionPairDiff.task_deltas`. It still
appears in :attr:`VersionPairDiff.matched_ids` (reported verbatim) and, when its
membership changes, in :attr:`~VersionPairDiff.added_ids` /
:attr:`~VersionPairDiff.deleted_ids`.

Error handling (LAW 2 -- never fabricate a delta): if ``order_versions`` raises
``VersionMatchError`` (a version lacks ``status_date``) or ``compute_cpm`` raises
``CPMError`` (a cycle / unsupported constraint), the exception propagates
unchanged. A single-version input is not an error: it yields an empty tuple of
pair diffs (there is no pair to compare).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from schedule_forensics.cpm import CPMResult, compute_cpm
from schedule_forensics.schemas import Schedule
from schedule_forensics.version_matcher import diff_versions, order_versions


@dataclass(frozen=True)
class TaskDelta:
    """The objective change for ONE task matched across a consecutive version pair.

    A ``TaskDelta`` is emitted only for a task whose ``unique_id`` is present, and
    scheduled (non-summary), in BOTH versions of the pair (added/deleted tasks
    have no counterpart to difference; they are reported as id sets on the
    enclosing :class:`VersionPairDiff`). Every numeric field is
    ``current - previous`` on the working-minute axis, so the sign is meaningful
    and hand-checkable.
    """

    unique_id: int
    duration_delta_minutes: int  # curr.duration_minutes - prev.duration_minutes
    total_float_delta_minutes: int  # curr.total_float - prev.total_float (working min)
    start_shift_minutes: int  # curr.early_start - prev.early_start (+ == later)
    finish_shift_minutes: int  # curr.early_finish - prev.early_finish (+ == later)
    became_critical: bool  # prev total_float > 0 and curr total_float <= 0
    recovered: bool  # prev total_float <= 0 and curr total_float > 0
    predecessors_added: tuple[int, ...]  # pred UniqueIDs new to this task in curr
    predecessors_removed: tuple[int, ...]  # pred UniqueIDs the task lost in curr


@dataclass(frozen=True)
class VersionPairDiff:
    """The objective delta between two consecutive versions (previous -> current).

    ``previous_status`` / ``current_status`` are the absolute status dates of the
    two versions (``datetime``, as ordered by ``order_versions`` -- carried
    through unchanged from ``version_matcher.diff_versions``, not re-stringified).
    ``matched_ids`` / ``added_ids`` / ``deleted_ids`` are the sorted UniqueID
    tuples taken verbatim from ``version_matcher.diff_versions``. ``task_deltas``
    is sorted by ``unique_id`` and covers exactly the matched tasks that are
    scheduled in both versions (see the module docstring).
    """

    previous_status: dt.datetime
    current_status: dt.datetime
    matched_ids: tuple[int, ...]
    added_ids: tuple[int, ...]
    deleted_ids: tuple[int, ...]
    task_deltas: tuple[TaskDelta, ...]


def _predecessor_ids(
    schedule: Schedule, scheduled_ids: frozenset[int]
) -> dict[int, frozenset[int]]:
    """Map each scheduled task ``unique_id`` -> the set of its scheduled predecessors.

    Built from ``schedule.relations`` (a predecessor of task S is any P with a
    link P -> S, regardless of link type or lag). Only links whose *both*
    endpoints are scheduled activities (in ``scheduled_ids``) are counted: a link
    touching a summary task is not a real-activity dependency -- consistent with
    the CPM network and :mod:`schedule_forensics.driving_path`. Every scheduled
    task gets an entry, even one with no predecessors (empty set), so a lookup
    never raises.
    """
    preds: dict[int, set[int]] = {tid: set() for tid in scheduled_ids}
    for rel in schedule.relations:
        if rel.predecessor_id in scheduled_ids and rel.successor_id in scheduled_ids:
            preds[rel.successor_id].add(rel.predecessor_id)
    return {tid: frozenset(ps) for tid, ps in preds.items()}


def _task_delta(
    unique_id: int,
    prev: Schedule,
    curr: Schedule,
    prev_cpm: CPMResult,
    curr_cpm: CPMResult,
    prev_preds: dict[int, frozenset[int]],
    curr_preds: dict[int, frozenset[int]],
) -> TaskDelta:
    """Compute the objective delta for one matched task.

    Caller guarantees the task is a scheduled activity in BOTH versions (present
    in both ``timings`` and both predecessor maps), so every lookup is total.
    """
    p_task = prev.task_by_id(unique_id)
    c_task = curr.task_by_id(unique_id)
    p_t = prev_cpm.timings[unique_id]
    c_t = curr_cpm.timings[unique_id]
    p_tf = p_t.total_float
    c_tf = c_t.total_float

    return TaskDelta(
        unique_id=unique_id,
        duration_delta_minutes=c_task.duration_minutes - p_task.duration_minutes,
        total_float_delta_minutes=c_tf - p_tf,
        start_shift_minutes=c_t.early_start - p_t.early_start,
        finish_shift_minutes=c_t.early_finish - p_t.early_finish,
        became_critical=p_tf > 0 and c_tf <= 0,
        recovered=p_tf <= 0 and c_tf > 0,
        predecessors_added=tuple(sorted(curr_preds[unique_id] - prev_preds[unique_id])),
        predecessors_removed=tuple(sorted(prev_preds[unique_id] - curr_preds[unique_id])),
    )


def diff_pair(
    prev: Schedule,
    curr: Schedule,
    prev_cpm: CPMResult,
    curr_cpm: CPMResult,
) -> VersionPairDiff:
    """Objective delta for an already-ordered ``(prev, curr)`` pair with their CPMs.

    ``prev`` / ``curr`` must already be in status-date order and ``prev_cpm`` /
    ``curr_cpm`` must be their respective :func:`~schedule_forensics.cpm.compute_cpm`
    results (:func:`diff_consecutive` guarantees both). Reuses
    :func:`~schedule_forensics.version_matcher.diff_versions` for the matched /
    added / deleted id sets (single source of truth) and emits a
    :class:`TaskDelta` for each matched task scheduled in both versions.
    """
    vd = diff_versions(prev, curr)  # also asserts both have a status_date

    prev_scheduled = frozenset(prev_cpm.timings)
    curr_scheduled = frozenset(curr_cpm.timings)
    prev_preds = _predecessor_ids(prev, prev_scheduled)
    curr_preds = _predecessor_ids(curr, curr_scheduled)

    deltas = tuple(
        _task_delta(uid, prev, curr, prev_cpm, curr_cpm, prev_preds, curr_preds)
        for uid in vd.matched_ids  # already sorted ascending by version_matcher
        if uid in prev_scheduled and uid in curr_scheduled
    )
    return VersionPairDiff(
        previous_status=vd.previous_status,
        current_status=vd.current_status,
        matched_ids=vd.matched_ids,
        added_ids=vd.added_ids,
        deleted_ids=vd.deleted_ids,
        task_deltas=deltas,
    )


def diff_consecutive(schedules: Sequence[Schedule]) -> tuple[VersionPairDiff, ...]:
    """Order versions by absolute ``status_date`` and diff each consecutive pair.

    Orders the versions via
    :func:`~schedule_forensics.version_matcher.order_versions`, computes the CPM
    for each version EXACTLY ONCE, then returns one :class:`VersionPairDiff` per
    adjacent (previous, current) pair, in chronological order.

    With fewer than two versions there is no pair to compare, so the result is an
    empty tuple -- but ordering is still validated eagerly so a missing
    ``status_date`` fails closed (LAW 2) rather than silently returning "no
    changes". Raises ``VersionMatchError`` if any version lacks ``status_date``
    and ``CPMError`` if any version cannot be scheduled -- both propagate
    unchanged (this module never fabricates a delta).
    """
    ordered = order_versions(schedules)
    if len(ordered) < 2:
        return ()
    cpms = [compute_cpm(s) for s in ordered]
    return tuple(
        diff_pair(ordered[i], ordered[i + 1], cpms[i], cpms[i + 1]) for i in range(len(ordered) - 1)
    )
