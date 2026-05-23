"""Objective version-delta tests against independently hand-computed values.

Every numeric expectation here is hand-derived from the CPM arithmetic shown in
each test's comment (default calendar: 480 working minutes == one 8-hour day),
NOT read back from the function's own output -- that is what makes the suite a
fidelity proof, not a tautology (LAW 2 / H-VACUOUS-TEST). Versions share
UniqueIDs and differ only in durations / logic / status_date.

Two networks recur:

LINEAR  A(1) -FS-> B(2) -FS-> C(3)            (single path; all tf == 0)
DIAMOND A(1) -> B(2) -> D(4); A(1) -> C(3) -> D(4)   (B long, C short w/ float)
"""

from __future__ import annotations

import datetime as dt

import pytest

from schedule_forensics.cpm import CPMError, compute_cpm
from schedule_forensics.diff_engine import (
    TaskDelta,
    VersionPairDiff,
    diff_consecutive,
    diff_pair,
)
from schedule_forensics.schemas import Relation, Schedule, Task
from schedule_forensics.version_matcher import VersionMatchError

_START = dt.datetime(2025, 1, 6, 8)  # a Monday, 08:00 (working-day start)
_S1 = dt.datetime(2025, 1, 6, 8)
_S2 = dt.datetime(2025, 1, 20, 8)  # 14 calendar days after _S1
_S3 = dt.datetime(2025, 2, 3, 8)  # 14 calendar days after _S2


def _sched(
    tasks: list[Task],
    relations: list[Relation],
    status: dt.datetime,
    name: str = "v",
) -> Schedule:
    return Schedule(
        name=name,
        project_start=_START,
        status_date=status,
        tasks=tuple(tasks),
        relations=tuple(relations),
    )


def _delta_for(diff: VersionPairDiff, uid: int) -> TaskDelta:
    matches = [d for d in diff.task_deltas if d.unique_id == uid]
    assert len(matches) == 1, f"expected exactly one delta for {uid}, got {len(matches)}"
    return matches[0]


# Diamond builders parametrised by the two variable durations (B long, C short).
def _diamond(b_dur: int, c_dur: int, status: dt.datetime) -> Schedule:
    tasks = [
        Task(unique_id=1, name="A", duration_minutes=480),
        Task(unique_id=2, name="B", duration_minutes=b_dur),
        Task(unique_id=3, name="C", duration_minutes=c_dur),
        Task(unique_id=4, name="D", duration_minutes=0, is_milestone=True),
    ]
    rels = [
        Relation(predecessor_id=1, successor_id=2),
        Relation(predecessor_id=1, successor_id=3),
        Relation(predecessor_id=2, successor_id=4),
        Relation(predecessor_id=3, successor_id=4),
    ]
    return _sched(tasks, rels, status)


def test_linear_chain_pure_duration_growth_shifts_successors() -> None:
    # LINEAR A(1d=480)->B(2d=960)->C(1d=480).
    #   v1: A es0 ef480; B es480 ef1440; C es1440 ef1920. All tf==0 (single path).
    #   v2: lengthen B to 3d=1440 (status _S2). A es0 ef480; B es480 ef1920;
    #       C es1920 ef2400. All tf still 0.
    # Deltas (curr - prev):
    #   A: dur 0, tf 0, start 0, finish 0.
    #   B: dur +480; start 0 (still es480); finish 1920-1440 = +480; tf 0.
    #   C: dur 0; start 1920-1440 = +480; finish 2400-1920 = +480; tf 0.
    v1 = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=960),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2), Relation(predecessor_id=2, successor_id=3)],
        _S1,
    )
    v2 = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=1440),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2), Relation(predecessor_id=2, successor_id=3)],
        _S2,
    )
    (pair,) = diff_consecutive([v2, v1])  # supplied out of order; must reorder by status
    assert pair.previous_status == _S1
    assert pair.current_status == _S2
    assert pair.matched_ids == (1, 2, 3)
    assert pair.added_ids == ()
    assert pair.deleted_ids == ()

    a = _delta_for(pair, 1)
    assert (a.duration_delta_minutes, a.start_shift_minutes, a.finish_shift_minutes) == (0, 0, 0)
    assert a.total_float_delta_minutes == 0

    b = _delta_for(pair, 2)
    assert b.duration_delta_minutes == 480
    assert b.start_shift_minutes == 0
    assert b.finish_shift_minutes == 480
    assert b.total_float_delta_minutes == 0

    c = _delta_for(pair, 3)
    assert c.duration_delta_minutes == 0
    assert c.start_shift_minutes == 480
    assert c.finish_shift_minutes == 480
    assert c.total_float_delta_minutes == 0
    assert all(not d.became_critical and not d.recovered for d in pair.task_deltas)


def test_diamond_total_float_delta_hand_computed() -> None:
    # DIAMOND, B fixed at 3d=1440. C grows 1d=480 -> 2d=960.
    #   v1 (C=480): A es0 ef480; B es480 ef1920; C es480 ef960; D es1920 ef1920.
    #     pf=1920. tf: A0, B0, D0; C: ls_C = 1920-480 = 1440 -> tf_C = 1440-480 = 960.
    #   v2 (C=960): A es0 ef480; B es480 ef1920; C es480 ef1440; D es1920 ef1920.
    #     pf=1920. tf_C: ls_C = 1920-960 = 960 -> tf_C = 960-480 = 480.
    # C total_float_delta = 480 - 960 = -480 (480 working min == 1 working day lost).
    # C duration_delta = 960 - 480 = +480. C early_start unchanged (es480) -> start 0.
    # C early_finish 1440-960 = +480. C stays non-critical both versions.
    v1 = _diamond(b_dur=1440, c_dur=480, status=_S1)
    v2 = _diamond(b_dur=1440, c_dur=960, status=_S2)
    (pair,) = diff_consecutive([v1, v2])

    c = _delta_for(pair, 3)
    assert c.total_float_delta_minutes == -480  # 960 -> 480 working minutes
    assert c.duration_delta_minutes == 480
    assert c.start_shift_minutes == 0
    assert c.finish_shift_minutes == 480
    assert c.became_critical is False  # still 480 > 0 working min of float
    assert c.recovered is False


def test_perturbation_became_critical_and_recovered_flip() -> None:
    # H-VACUOUS-TEST: a float crossing must flip became_critical (and the inverse
    # crossing must flip recovered). Asserting BOTH states proves the calc is read.
    #
    # v1 DIAMOND B=3d=1440, C=1d=480:
    #   tf_B = 0 (critical); tf_C = 960 (> 0, NOT critical) -- as computed above.
    # v2 lengthen C to 4d=1920 (now the long branch); B unchanged.
    #   A es0 ef480; B es480 ef1920; C es480 ef2400; D es2400 ef2400. pf=2400.
    #   Backward: D lf2400; C lf2400 ls480 -> tf_C = 0 (NOW critical);
    #   B lf2400 ls960 -> tf_B = 960-480 = 480 (> 0, NOW has float).
    # So across v1->v2: C crosses 960->0  => became_critical True, recovered False.
    #                   B crosses 0->480  => recovered True,       became_critical False.
    v1 = _diamond(b_dur=1440, c_dur=480, status=_S1)
    v2 = _diamond(b_dur=1440, c_dur=1920, status=_S2)

    (before_pair,) = diff_consecutive([v1, v1_clone := _diamond(1440, 480, _S2)])
    # In a no-change pair, nobody flips (sanity anchor for the perturbation).
    assert all(not d.became_critical and not d.recovered for d in before_pair.task_deltas)
    assert v1_clone is not v1

    (pair,) = diff_consecutive([v1, v2])
    c = _delta_for(pair, 3)
    b = _delta_for(pair, 2)
    assert c.became_critical is True
    assert c.recovered is False
    assert c.total_float_delta_minutes == -960  # 960 -> 0
    assert b.recovered is True
    assert b.became_critical is False
    assert b.total_float_delta_minutes == 480  # 0 -> 480


def test_added_and_deleted_ids_propagate() -> None:
    # v1 has tasks {1,2}; v2 adds task 3 and deletes task 2 (matched set = {1}).
    #   matched_ids=(1,), added_ids=(3,), deleted_ids=(2,). Only task 1 gets a delta.
    v1 = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
        _S1,
    )
    v2 = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=3)],
        _S2,
    )
    (pair,) = diff_consecutive([v1, v2])
    assert pair.matched_ids == (1,)
    assert pair.added_ids == (3,)
    assert pair.deleted_ids == (2,)
    assert tuple(d.unique_id for d in pair.task_deltas) == (1,)


def test_predecessor_add_and_remove_detection() -> None:
    # Three tasks 1,2,3. v1: only 1->3. v2: add 2->3 and remove 1->3, plus 1->2.
    #   Task 3 predecessors: v1 {1}; v2 {2}. So added={2}, removed={1}.
    #   Task 2 predecessors: v1 {} ; v2 {1}. So added={1}, removed={}.
    # Durations equal so this isolates pure-logic deltas. Hand-check the sets only.
    v1 = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=3)],
        _S1,
    )
    v2 = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=3),
        ],
        _S2,
    )
    (pair,) = diff_consecutive([v1, v2])
    three = _delta_for(pair, 3)
    assert three.predecessors_added == (2,)
    assert three.predecessors_removed == (1,)
    two = _delta_for(pair, 2)
    assert two.predecessors_added == (1,)
    assert two.predecessors_removed == ()
    # Task 1 never had/has a predecessor.
    one = _delta_for(pair, 1)
    assert one.predecessors_added == ()
    assert one.predecessors_removed == ()


def test_three_versions_yield_two_consecutive_pairs_in_order() -> None:
    # Supplied scrambled; must order by status_date and emit pairs (S1->S2),(S2->S3).
    a = _diamond(1440, 480, _S1)
    b = _diamond(1440, 960, _S2)
    c = _diamond(1440, 1200, _S3)
    pairs = diff_consecutive([c, a, b])
    assert len(pairs) == 2
    assert (pairs[0].previous_status, pairs[0].current_status) == (_S1, _S2)
    assert (pairs[1].previous_status, pairs[1].current_status) == (_S2, _S3)


def test_single_version_yields_empty_tuple() -> None:
    # A 1-version input has no consecutive pair to compare.
    only = _diamond(1440, 480, _S1)
    assert diff_consecutive([only]) == ()


def test_empty_input_yields_empty_tuple_via_order_versions_guard() -> None:
    # order_versions raises on an empty sequence; the >=2 guard never masks it.
    with pytest.raises(VersionMatchError):
        diff_consecutive([])


def test_missing_status_date_propagates() -> None:
    # A version without status_date cannot be ordered: VersionMatchError propagates,
    # never a fabricated "no change" result (LAW 2, fail closed).
    good = _diamond(1440, 480, _S1)
    bad = Schedule(
        name="nostatus",
        project_start=_START,
        status_date=None,
        tasks=(Task(unique_id=1, name="A", duration_minutes=480),),
    )
    with pytest.raises(VersionMatchError):
        diff_consecutive([good, bad])


def test_cycle_propagates_cpm_error() -> None:
    # An unschedulable later version must raise (from CPM), not invent a delta.
    v1 = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
        _S1,
    )
    cyclic = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=1),
        ],
        _S2,
    )
    with pytest.raises(CPMError):
        diff_consecutive([v1, cyclic])


def test_matched_summary_task_is_excluded_from_deltas_but_visible_in_matched_ids() -> None:
    # A task that is a SUMMARY in both versions is absent from CPM timings, so it
    # gets no TaskDelta -- but it IS still reported in matched_ids (visible).
    # Tasks: 1 summary (matched), 2 real A, 3 real B with 2->3 link.
    #   Real network: A es0 ef480; B es480 ef960. v2 lengthens B to 2d=960.
    def build(b_dur: int, status: dt.datetime) -> Schedule:
        return _sched(
            [
                Task(unique_id=1, name="Phase", duration_minutes=0, is_summary=True),
                Task(unique_id=2, name="A", duration_minutes=480),
                Task(unique_id=3, name="B", duration_minutes=b_dur),
            ],
            [Relation(predecessor_id=2, successor_id=3)],
            status,
        )

    v1 = build(480, _S1)
    v2 = build(960, _S2)
    (pair,) = diff_consecutive([v1, v2])
    assert 1 in pair.matched_ids  # summary still reported as matched
    assert all(d.unique_id != 1 for d in pair.task_deltas)  # but no delta for it
    b = _delta_for(pair, 3)
    assert b.duration_delta_minutes == 480  # the real task's delta is computed


def test_diff_pair_reuses_supplied_cpm_results() -> None:
    # diff_pair operates on already-ordered versions + their CPMs (no recompute
    # of ordering); it must agree with diff_consecutive's single pair.
    v1 = _diamond(1440, 480, _S1)
    v2 = _diamond(1440, 960, _S2)
    via_pair = diff_pair(v1, v2, compute_cpm(v1), compute_cpm(v2))
    (via_consecutive,) = diff_consecutive([v1, v2])
    assert via_pair == via_consecutive
