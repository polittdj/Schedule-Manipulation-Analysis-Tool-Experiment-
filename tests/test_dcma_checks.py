"""DCMA-14 structural-check tests against independently hand-computed values.

Every numeric expectation here is hand-derived (the arithmetic is shown in each
test's comment) and NEVER read back from the function under test -- that is what
makes this a fidelity proof rather than a tautology (LAW 2 / H-VACUOUS-TEST).

Axis: the default calendar is 480 working minutes per day, matching
:mod:`schedule_forensics.cpm`. The DCMA "44 working days" threshold used by the
High-Float (M6) and High-Duration (M8) checks is ``44 * 480 == 21120`` working
minutes. CPM total-float values used below were cross-checked against
``compute_cpm`` by hand-tracing the forward/backward pass (shown inline).

Perturbation discipline (H-VACUOUS-TEST): M4 has a PASS case whose single flip
FS->SS drops it below 90% and to FAIL; M7 has a clean PASS case and a
deadline-induced negative-float FAIL case. Skip paths (empty relations -> M2/M3/M4
skipped; CPMError -> M6/M7 skipped) are exercised explicitly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from schedule_forensics.cpm import CPMError, compute_cpm
from schedule_forensics.dcma_checks import (
    _FORTY_FOUR_DAYS_MIN,
    THRESHOLD_HARD_CONSTRAINTS,
    THRESHOLD_HIGH_DURATION,
    THRESHOLD_HIGH_FLOAT,
    THRESHOLD_LAGS,
    THRESHOLD_LEADS,
    THRESHOLD_MISSING_LOGIC,
    THRESHOLD_NEGATIVE_FLOAT,
    THRESHOLD_RELATIONSHIP_TYPES,
    check_hard_constraints,
    check_high_duration,
    check_high_float,
    check_lags,
    check_leads,
    check_missing_logic,
    check_negative_float,
    check_relationship_types,
    run_structural_checks,
)
from schedule_forensics.metrics_common import Direction, MetricStatus
from schedule_forensics.schemas import (
    ConstraintType,
    Relation,
    RelationType,
    Schedule,
    Task,
)

_START = dt.datetime(2025, 1, 6, 8)  # a Monday, working-day start


def _sched(tasks: Iterable[Task], relations: Iterable[Relation] = ()) -> Schedule:
    return Schedule(name="t", project_start=_START, tasks=tuple(tasks), relations=tuple(relations))


# A single registry of (id -> (Threshold, expected_direction, expected_value)) so
# the threshold table is asserted in one place (H-DRIFT-2 parity test below).
_THRESHOLDS = {
    "DCMA-01": (THRESHOLD_MISSING_LOGIC, Direction.LE, 5.0),
    "DCMA-02": (THRESHOLD_LEADS, Direction.EQ, 0.0),
    "DCMA-03": (THRESHOLD_LAGS, Direction.LE, 5.0),
    "DCMA-04": (THRESHOLD_RELATIONSHIP_TYPES, Direction.GE, 90.0),
    "DCMA-05": (THRESHOLD_HARD_CONSTRAINTS, Direction.LE, 5.0),
    "DCMA-06": (THRESHOLD_HIGH_FLOAT, Direction.LE, 5.0),
    "DCMA-07": (THRESHOLD_NEGATIVE_FLOAT, Direction.EQ, 0.0),
    "DCMA-08": (THRESHOLD_HIGH_DURATION, Direction.LE, 5.0),
}


# --------------------------------------------------------------------------- #
# Threshold single-source-of-truth + citation (H-DRIFT-2, parity honesty)
# --------------------------------------------------------------------------- #
def test_thresholds_have_canonical_values_directions_and_cited_source() -> None:
    # Canonical DCMA 14-Point values + directions, asserted once. A perturbation
    # of any constant (value or direction) fails here -- this proves the detector
    # is not vacuous (H-DRIFT-2).
    for metric_id, (threshold, direction, value) in _THRESHOLDS.items():
        assert threshold.value == value, metric_id
        assert threshold.direction is direction, metric_id
        assert threshold.source, f"{metric_id} threshold has an empty source"
        # Honesty: page anchor is declared source-pending, never a fabricated page.
        assert "source-pending" in threshold.source, metric_id


def test_forty_four_day_threshold_is_exactly_21120_minutes() -> None:
    # Single source of truth for the working-minute conversion: 44 * 480 == 21120.
    assert _FORTY_FOUR_DAYS_MIN == 44 * 480 == 21120


# --------------------------------------------------------------------------- #
# DCMA-01 Missing Logic
# --------------------------------------------------------------------------- #
def test_missing_logic_open_ends_counted_once_with_two_offenders() -> None:
    # Chain A->B->C (3 non-summary tasks). A lacks a predecessor; C lacks a
    # successor; B is fully linked. Dangling task COUNT = 2 of 3 = 66.66...% > 5%
    # => FAIL. Offenders: A(missing_predecessor), C(missing_successor) = 2 rows.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=3),
        ],
    )
    result = check_missing_logic(schedule)
    assert result.status is MetricStatus.FAIL
    # 2 dangling of 3 tasks. The percentage is 2/3 * 100; assert it in the metric's
    # own association (100*n/d) so the comparison is exact, not float-approximate
    # (H-DRIFT-1 forbids tolerance on user-facing numbers). 100*2/3 == 66.666...67.
    assert result.measured == 100.0 * 2 / 3
    assert len(result.offenders) == 2
    kinds = {(o.unique_id, o.kind) for o in result.offenders}
    assert kinds == {(1, "missing_predecessor"), (3, "missing_successor")}


def test_missing_logic_isolated_task_yields_two_offenders_but_counts_once() -> None:
    # Two tasks; only 1->2 linked, plus an isolated task 3 (no links at all).
    # Dangling task count: task1 missing predecessor, task2 missing successor,
    # task3 missing BOTH -> distinct dangling ids {1,2,3} = 3 of 3 = 100%.
    # Offender ROWS: 1(missing_predecessor), 2(missing_successor),
    # 3(missing_predecessor)+3(missing_successor) = 4 rows. Task 3 counted ONCE
    # in the numerator (one task) but emits two offender rows (one per side).
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
            Task(unique_id=3, name="Island", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    result = check_missing_logic(schedule)
    assert result.measured == 100.0  # 3 distinct dangling tasks / 3 tasks
    assert len(result.offenders) == 4
    task3_rows = {o.kind for o in result.offenders if o.unique_id == 3}
    assert task3_rows == {"missing_predecessor", "missing_successor"}


def test_missing_logic_links_through_summary_do_not_count() -> None:
    # Task A links only to a SUMMARY task S; the summary is excluded from scope,
    # so A is treated as having no successor (its only link's other end is a
    # summary). Non-summary tasks = {A}. A lacks both sides -> 1 of 1 = 100%.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="S", duration_minutes=480, is_summary=True),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    result = check_missing_logic(schedule)
    assert result.measured == 100.0
    assert len(result.offenders) == 2  # A missing pred + A missing succ
    assert all(o.unique_id == 1 for o in result.offenders)


def test_missing_logic_passes_when_under_five_percent() -> None:
    # 21 tasks in a single FS chain 1->2->...->21. Only the two bookends dangle:
    # task1 (no predecessor) and task21 (no successor) = 2 dangling / 21 tasks
    # = 9.52% > 5% => FAIL. To get a PASS we need >= 40 tasks so 2/N <= 5%.
    # Build a 40-task chain: 2/40 = 5.0% which is exactly <= 5% => PASS.
    tasks = [Task(unique_id=i, name=f"T{i}", duration_minutes=480) for i in range(1, 41)]
    relations = [Relation(predecessor_id=i, successor_id=i + 1) for i in range(1, 40)]
    result = check_missing_logic(_sched(tasks, relations))
    assert result.measured == 2 / 40 * 100.0  # 5.0
    assert result.status is MetricStatus.PASS


# --------------------------------------------------------------------------- #
# DCMA-02 Leads
# --------------------------------------------------------------------------- #
def test_leads_counts_negative_lag_relationships() -> None:
    # Two relations, one with lag -480 (a lead). measured == COUNT of leads == 1,
    # threshold == 0 (EQ) => FAIL. Offender keys on the successor (task pulled
    # earlier) with value == -480.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2, lag_minutes=-480),
            Relation(predecessor_id=2, successor_id=3, lag_minutes=0),
        ],
    )
    result = check_leads(schedule)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1.0
    assert len(result.offenders) == 1
    off = result.offenders[0]
    assert off.unique_id == 2 and off.kind == "lead_minutes" and off.value == -480.0


def test_leads_passes_with_no_negative_lag() -> None:
    # One FS link, lag 0 -> zero leads. measured == 0 == threshold => PASS.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2, lag_minutes=0)],
    )
    result = check_leads(schedule)
    assert result.status is MetricStatus.PASS
    assert result.measured == 0.0
    assert result.offenders == ()


def test_leads_skipped_when_no_relationships() -> None:
    schedule = _sched([Task(unique_id=1, name="A", duration_minutes=480)])
    result = check_leads(schedule)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None
    assert result.detail  # a non-empty reason, never a fabricated 0


# --------------------------------------------------------------------------- #
# DCMA-03 Lags
# --------------------------------------------------------------------------- #
def test_lags_percentage_of_positive_lag_relationships() -> None:
    # 4 relations, 1 with positive lag (+240). 1/4 = 25% > 5% => FAIL.
    schedule = _sched(
        [Task(unique_id=i, name=f"T{i}", duration_minutes=480) for i in range(1, 6)],
        [
            Relation(predecessor_id=1, successor_id=2, lag_minutes=240),
            Relation(predecessor_id=2, successor_id=3, lag_minutes=0),
            Relation(predecessor_id=3, successor_id=4, lag_minutes=0),
            Relation(predecessor_id=4, successor_id=5, lag_minutes=-60),  # lead, not a lag
        ],
    )
    result = check_lags(schedule)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1 / 4 * 100.0  # 25.0; the -60 lead is NOT a lag
    assert len(result.offenders) == 1
    assert result.offenders[0].unique_id == 2 and result.offenders[0].value == 240.0


def test_lags_passes_under_five_percent() -> None:
    # 20 relations in a chain, exactly 1 positive lag -> 1/20 = 5.0% <= 5% => PASS.
    tasks = [Task(unique_id=i, name=f"T{i}", duration_minutes=480) for i in range(1, 22)]
    relations = [
        Relation(predecessor_id=i, successor_id=i + 1, lag_minutes=(240 if i == 1 else 0))
        for i in range(1, 21)
    ]
    result = check_lags(_sched(tasks, relations))
    assert result.measured == 1 / 20 * 100.0  # 5.0
    assert result.status is MetricStatus.PASS


def test_lags_skipped_when_no_relationships() -> None:
    result = check_lags(_sched([Task(unique_id=1, name="A", duration_minutes=480)]))
    assert result.status is MetricStatus.SKIPPED


# --------------------------------------------------------------------------- #
# DCMA-04 Relationship Types (+ perturbation: H-VACUOUS-TEST)
# --------------------------------------------------------------------------- #
def test_relationship_types_all_fs_passes_at_100_percent() -> None:
    # 10 FS links -> 100% FS >= 90% => PASS, no offenders.
    tasks = [Task(unique_id=i, name=f"T{i}", duration_minutes=480) for i in range(1, 12)]
    relations = [Relation(predecessor_id=i, successor_id=i + 1) for i in range(1, 11)]
    result = check_relationship_types(_sched(tasks, relations))
    assert result.measured == 100.0
    assert result.status is MetricStatus.PASS
    assert result.offenders == ()


def test_relationship_types_perturbation_one_flip_drops_below_90_and_fails() -> None:
    # Baseline: 10 FS links -> 100% PASS. PERTURB: flip ONE link FS->SS.
    # FS share becomes 9/10 = 90.0% which is >= 90 (still PASS at exactly 90).
    # To force the FAIL, flip with 9 links: 8 FS of 9 = 88.88% < 90 => FAIL.
    # This proves the metric actually reads relationship type (H-VACUOUS-TEST):
    # the same network with all-FS PASSes, and the single SS flip FAILs.
    tasks = [Task(unique_id=i, name=f"T{i}", duration_minutes=480) for i in range(1, 11)]
    base_rels = [Relation(predecessor_id=i, successor_id=i + 1) for i in range(1, 10)]  # 9 FS
    base = check_relationship_types(_sched(tasks, base_rels))
    assert base.measured == 100.0 and base.status is MetricStatus.PASS

    perturbed_rels = [
        Relation(predecessor_id=i, successor_id=i + 1, type=RelationType.SS)
        if i == 1
        else Relation(predecessor_id=i, successor_id=i + 1)
        for i in range(1, 10)
    ]
    perturbed = check_relationship_types(_sched(tasks, perturbed_rels))
    assert perturbed.measured == 8 / 9 * 100.0  # 88.888... < 90
    assert perturbed.status is MetricStatus.FAIL
    assert len(perturbed.offenders) == 1
    off = perturbed.offenders[0]
    assert off.unique_id == 2 and off.kind == "non_fs_relationship"


def test_relationship_types_exactly_90_percent_passes() -> None:
    # 10 links, 9 FS + 1 SS -> 9/10 = 90.0% which is >= 90 => PASS (boundary).
    tasks = [Task(unique_id=i, name=f"T{i}", duration_minutes=480) for i in range(1, 12)]
    relations = [
        Relation(predecessor_id=i, successor_id=i + 1, type=RelationType.SS)
        if i == 1
        else Relation(predecessor_id=i, successor_id=i + 1)
        for i in range(1, 11)
    ]
    result = check_relationship_types(_sched(tasks, relations))
    assert result.measured == 90.0
    assert result.status is MetricStatus.PASS


def test_relationship_types_skipped_when_no_relationships() -> None:
    result = check_relationship_types(_sched([Task(unique_id=1, name="A", duration_minutes=480)]))
    assert result.status is MetricStatus.SKIPPED


# --------------------------------------------------------------------------- #
# DCMA-05 Hard Constraints
# --------------------------------------------------------------------------- #
def test_hard_constraints_counts_only_hard_types() -> None:
    # 4 non-summary tasks: SNLT (hard), FNLT (hard), SNET (SOFT), ASAP (none).
    # Hard = 2 of 4 = 50% > 5% => FAIL. Offenders are the two hard-constrained.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                constraint_type=ConstraintType.SNLT,
                constraint_date=_START,
            ),
            Task(
                unique_id=2,
                name="B",
                duration_minutes=480,
                constraint_type=ConstraintType.FNLT,
                constraint_date=_START,
            ),
            Task(
                unique_id=3,
                name="C",
                duration_minutes=480,
                constraint_type=ConstraintType.SNET,  # soft -> not counted
                constraint_date=_START,
            ),
            Task(unique_id=4, name="D", duration_minutes=480),  # ASAP default
        ],
    )
    result = check_hard_constraints(schedule)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 2 / 4 * 100.0  # 50.0
    assert {o.unique_id for o in result.offenders} == {1, 2}


def test_hard_constraints_mso_mfo_are_hard_and_summaries_excluded() -> None:
    # MSO + MFO are hard. A SUMMARY task with MSO must be ignored (summaries are
    # out of scope). Non-summary tasks: MSO(hard), MFO(hard), ASAP. 2 of 3 hard.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                constraint_type=ConstraintType.MSO,
                constraint_date=_START,
            ),
            Task(
                unique_id=2,
                name="B",
                duration_minutes=480,
                constraint_type=ConstraintType.MFO,
                constraint_date=_START,
            ),
            Task(unique_id=3, name="C", duration_minutes=480),
            Task(
                unique_id=4,
                name="Summary",
                duration_minutes=0,
                is_summary=True,
                constraint_type=ConstraintType.MSO,
                constraint_date=_START,
            ),
        ],
    )
    result = check_hard_constraints(schedule)
    # 2 hard of 3 non-summary (summary task 4 excluded). Assert in the metric's own
    # association (100*n/d) for an exact compare. 100*2/3 == 66.666...67.
    assert result.measured == 100.0 * 2 / 3
    assert {o.unique_id for o in result.offenders} == {1, 2}


def test_hard_constraints_passes_when_all_soft_or_none() -> None:
    # SNET (soft) + ASAP (none) -> 0 hard of 2 = 0% <= 5% => PASS.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                constraint_type=ConstraintType.SNET,
                constraint_date=_START,
            ),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
    )
    result = check_hard_constraints(schedule)
    assert result.measured == 0.0
    assert result.status is MetricStatus.PASS


def test_hard_constraints_skipped_when_no_non_summary_tasks() -> None:
    schedule = _sched(
        [Task(unique_id=1, name="S", duration_minutes=0, is_summary=True)],
    )
    result = check_hard_constraints(schedule)
    assert result.status is MetricStatus.SKIPPED


# --------------------------------------------------------------------------- #
# DCMA-06 High Float (CPM-dependent)
# --------------------------------------------------------------------------- #
def test_high_float_flags_task_over_44_days() -> None:
    # Network: X(24000 min)->Z(480); Y(480)->Z(480). Forward pass:
    #   X es0 ef24000; Y es0 ef480; Z waits max(24000,480)=24000, es24000 ef24480.
    #   project_finish = 24480.
    # Backward: Z lf24480 ls24000; X (FS->Z) lf=ls_Z=24000 -> float 24000-24000=0;
    #   Y (FS->Z) lf=ls_Z=24000, ls=23520 -> float 23520-0 = 23520.
    # 23520 > 21120 => Y is high-float. 1 of 3 incomplete tasks = 33.33% > 5% FAIL.
    schedule = _sched(
        [
            Task(unique_id=1, name="X", duration_minutes=24000),
            Task(unique_id=2, name="Y", duration_minutes=480),
            Task(unique_id=3, name="Z", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=3),
        ],
    )
    cpm = compute_cpm(schedule)
    # Cross-check the float the metric will read (hand-traced above == engine).
    assert cpm.timings[2].total_float == 23520
    result = check_high_float(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    # 1 high-float (Y) of 3 incomplete tasks. Assert in the metric's own
    # association (100*n/d) for an exact compare. 100*1/3 == 33.333...36.
    assert result.measured == 100.0 * 1 / 3
    assert len(result.offenders) == 1
    off = result.offenders[0]
    assert off.unique_id == 2 and off.kind == "total_float_minutes" and off.value == 23520.0


def test_high_float_passes_when_all_floats_within_44_days() -> None:
    # A->B->C linear, each 480; all floats 0 (every task critical). 0 high-float
    # of 3 incomplete = 0% <= 5% => PASS.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=3),
        ],
    )
    cpm = compute_cpm(schedule)
    result = check_high_float(schedule, cpm)
    assert result.measured == 0.0
    assert result.status is MetricStatus.PASS


def test_high_float_at_exactly_44_days_is_not_an_offender() -> None:
    # Boundary: float == 21120 is NOT > 21120, so it does not offend.
    # Spine X(21600=45d)->Z(480); Y(480)->Z. Z es21600 ef22080. Y float:
    #   ls_Z = 21600; Y lf=21600 ls=21120 -> float 21120-0 = 21120 == threshold.
    schedule = _sched(
        [
            Task(unique_id=1, name="X", duration_minutes=21600),
            Task(unique_id=2, name="Y", duration_minutes=480),
            Task(unique_id=3, name="Z", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=3),
        ],
    )
    cpm = compute_cpm(schedule)
    assert cpm.timings[2].total_float == 21120  # exactly 44 working days
    result = check_high_float(schedule, cpm)
    assert result.measured == 0.0  # 21120 is not strictly greater than 21120
    assert result.status is MetricStatus.PASS


def test_high_float_excludes_completed_tasks() -> None:
    # Same high-float network, but mark the offending task Y 100% complete. It is
    # then excluded from the incomplete denominator AND cannot be an offender.
    # Remaining incomplete tasks X, Z both have float 0 -> 0 of 2 = 0% => PASS.
    schedule = _sched(
        [
            Task(unique_id=1, name="X", duration_minutes=24000),
            Task(unique_id=2, name="Y", duration_minutes=480, percent_complete=100.0),
            Task(unique_id=3, name="Z", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=3),
        ],
    )
    cpm = compute_cpm(schedule)
    result = check_high_float(schedule, cpm)
    assert result.measured == 0.0  # only X, Z counted; Y (100%) excluded
    assert result.status is MetricStatus.PASS
    assert result.offenders == ()


# --------------------------------------------------------------------------- #
# DCMA-07 Negative Float (CPM-dependent) (+ perturbation: H-VACUOUS-TEST)
# --------------------------------------------------------------------------- #
def test_negative_float_clean_network_passes() -> None:
    # A->B linear, each 480, no imposed finish -> floats 0. 0 negative of 2 = 0%
    # == threshold => PASS. (The clean half of the M7 perturbation pair.)
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    cpm = compute_cpm(schedule)
    result = check_negative_float(schedule, cpm)
    assert result.measured == 0.0
    assert result.status is MetricStatus.PASS


def test_negative_float_deadline_perturbation_forces_failure() -> None:
    # PERTURB the clean A->B network by imposing a deadline on B at the project
    # start (offset 0), earlier than the network finish (960). Backward pass caps
    # B.lf at 0 -> B float = ls(-480) - es(480) = ... engine yields -960 for both
    # A and B (the cap propagates back through the FS link). 2 of 2 negative =
    # 100% > 0 => FAIL. Same tasks/logic as the PASS case; ONLY the deadline
    # changed -- proving the check actually reads CPM float (H-VACUOUS-TEST).
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(
                unique_id=2,
                name="B",
                duration_minutes=480,
                deadline=dt.datetime(2025, 1, 6, 8),  # offset 0, before finish 960
            ),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    cpm = compute_cpm(schedule)
    assert cpm.timings[1].total_float == -960  # hand-traced; cap propagates back
    assert cpm.timings[2].total_float == -960
    result = check_negative_float(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 100.0  # 2 of 2 tasks negative
    assert {o.unique_id for o in result.offenders} == {1, 2}
    assert all(o.value == -960.0 for o in result.offenders)


# --------------------------------------------------------------------------- #
# DCMA-08 High Duration
# --------------------------------------------------------------------------- #
def test_high_duration_flags_tasks_over_44_days() -> None:
    # 4 incomplete tasks: durations 21121 (>44d), 21120 (==44d, not over),
    # 480, 0. Only the 21121-min task offends. 1 of 4 = 25% > 5% => FAIL.
    schedule = _sched(
        [
            Task(unique_id=1, name="Long", duration_minutes=21121),
            Task(unique_id=2, name="Exactly44d", duration_minutes=21120),
            Task(unique_id=3, name="Short", duration_minutes=480),
            Task(unique_id=4, name="Milestone", duration_minutes=0),
        ],
    )
    result = check_high_duration(schedule)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1 / 4 * 100.0  # 25.0
    assert len(result.offenders) == 1
    off = result.offenders[0]
    assert off.unique_id == 1 and off.kind == "duration_minutes" and off.value == 21121.0


def test_high_duration_excludes_completed_and_summary_tasks() -> None:
    # A long (>44d) task that is 100% complete is excluded (incomplete-only). A
    # long SUMMARY task is excluded (non-summary only). The only remaining task
    # is a short incomplete one -> 0 of 1 = 0% => PASS.
    schedule = _sched(
        [
            Task(unique_id=1, name="DoneLong", duration_minutes=30000, percent_complete=100.0),
            Task(unique_id=2, name="SummaryLong", duration_minutes=30000, is_summary=True),
            Task(unique_id=3, name="Short", duration_minutes=480),
        ],
    )
    result = check_high_duration(schedule)
    assert result.measured == 0.0
    assert result.status is MetricStatus.PASS
    assert result.offenders == ()


def test_high_duration_skipped_when_no_incomplete_tasks() -> None:
    # All tasks complete -> empty incomplete denominator -> SKIPPED (no fake 0%).
    schedule = _sched(
        [Task(unique_id=1, name="A", duration_minutes=480, percent_complete=100.0)],
    )
    result = check_high_duration(schedule)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


# --------------------------------------------------------------------------- #
# run_structural_checks orchestration + CPM-skip handling
# --------------------------------------------------------------------------- #
def test_run_structural_checks_returns_eight_in_id_order() -> None:
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    results = run_structural_checks(schedule)
    ids = [r.metric_id for r in results]
    assert ids == [f"DCMA-0{i}" for i in range(1, 9)]
    # Every returned result cites a non-empty source unless it is SKIPPED (a skip
    # carries no threshold/source by contract). Run checks here all execute.
    for r in results:
        if r.status is not MetricStatus.SKIPPED:
            assert r.source, f"{r.metric_id} returned an empty source"


def test_run_structural_checks_skips_float_checks_on_cpm_error() -> None:
    # An MSO constraint makes the CPM raise (deferred constraint). M6 (High Float)
    # and M7 (Negative Float) must become SKIPPED with the CPM error in the
    # reason; the six structural checks still run (PASS/FAIL).
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                constraint_type=ConstraintType.MSO,
                constraint_date=_START,
            ),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    # Sanity: confirm the engine truly raises on this input (so the skip is real).
    raised = False
    try:
        compute_cpm(schedule)
    except CPMError:
        raised = True
    assert raised, "fixture must make compute_cpm raise for the skip path to be meaningful"

    results = {r.metric_id: r for r in run_structural_checks(schedule)}
    assert results["DCMA-06"].status is MetricStatus.SKIPPED
    assert results["DCMA-07"].status is MetricStatus.SKIPPED
    assert "CPM" in results["DCMA-06"].detail  # the CPM error is surfaced, not swallowed
    # The non-CPM checks still produced a verdict (e.g. DCMA-05 sees the hard MSO).
    assert results["DCMA-05"].status in (MetricStatus.PASS, MetricStatus.FAIL)
    assert results["DCMA-04"].status is MetricStatus.PASS  # the single FS link is 100% FS


def test_run_structural_checks_reuses_supplied_cpm_result() -> None:
    # When a CPMResult is supplied, run_* must reuse it (M6/M7 run, not skip).
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    cpm = compute_cpm(schedule)
    results = {r.metric_id: r for r in run_structural_checks(schedule, cpm)}
    assert results["DCMA-06"].status is MetricStatus.PASS  # floats 0, ran (not skipped)
    assert results["DCMA-07"].status is MetricStatus.PASS
