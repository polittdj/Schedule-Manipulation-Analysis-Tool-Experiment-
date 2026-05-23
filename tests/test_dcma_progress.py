"""DCMA-14 progress-check tests (Metrics 9-14) against hand-computed values.

Every numeric expectation here is hand-derived (the arithmetic is shown in each
test's comment) and NEVER read back from the function under test -- that is what
makes this a fidelity proof rather than a tautology (LAW 2 / H-VACUOUS-TEST).

Axis: the default calendar is 480 working minutes per day, matching
:mod:`schedule_forensics.cpm`. ``project_start`` is fixed at Monday 2025-01-06
08:00 (a working-day start). With that start the working-minute offsets used
below are: Mon Jan6 = 0, Tue Jan7 = 480, Wed Jan8 = 960, Thu Jan9 = 1440,
Fri Jan10 = 1920, Mon Jan13 = 2400 (the weekend contributes no working minutes).
These were cross-checked against
:func:`~schedule_forensics.cpm.datetime_to_offset` and are restated in the
``_offset`` helper's comment.

Perturbation discipline (H-VACUOUS-TEST):
  * DCMA-14 (BEI): a schedule where every due task is complete PASSES; clearing
    ONE due task's ``actual_finish`` flips BEI below 0.95 to FAIL. Both asserted.
  * DCMA-12 (Critical Path Test): a linear network PASSES (the injected delay
    flows to the finish); a network whose chosen critical task does NOT drive the
    finish (its delay is absorbed because a parallel longer chain governs) FAILS.

Skip paths exercised explicitly: no status_date (M9/M13/M14), no baseline
(M11/M14 via empty denominator), CPMError via a cyclic schedule (M9/M11/M12/M13
skip while M10/M14 still run), degenerate CPLI (status at/after forecast finish),
and no critical task with duration > 0 (M12).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from schedule_forensics.cpm import CPMError, compute_cpm, datetime_to_offset
from schedule_forensics.dcma_progress import (
    _CRITICAL_PATH_TEST_DELAY_MIN,
    THRESHOLD_BEI,
    THRESHOLD_CPLI,
    THRESHOLD_CRITICAL_PATH_TEST,
    THRESHOLD_INVALID_DATES,
    THRESHOLD_MISSED_TASKS,
    THRESHOLD_RESOURCES,
    check_bei,
    check_cpli,
    check_critical_path_test,
    check_invalid_dates,
    check_missed_tasks,
    check_resources,
    run_progress_checks,
)
from schedule_forensics.metrics_common import Direction, MetricStatus
from schedule_forensics.schemas import (
    ConstraintType,
    Relation,
    Schedule,
    Task,
)

_START = dt.datetime(2025, 1, 6, 8)  # a Monday, working-day start (offset 0)


def _sched(
    tasks: Iterable[Task],
    relations: Iterable[Relation] = (),
    *,
    status_date: dt.datetime | None = None,
    baseline_finish: dt.datetime | None = None,
) -> Schedule:
    return Schedule(
        name="t",
        project_start=_START,
        status_date=status_date,
        baseline_finish=baseline_finish,
        tasks=tuple(tasks),
        relations=tuple(relations),
    )


def _offset(target: dt.datetime) -> int:
    """Working-minute offset of ``target`` from ``_START`` (Mon Jan6 08:00).

    Hand-reference (default calendar, 480 min/day, Mon-Fri):
      Tue Jan7 -> 480, Wed Jan8 -> 960, Thu Jan9 -> 1440, Fri Jan10 -> 1920,
      Mon Jan13 -> 2400. Used only inside tests to keep date<->offset reasoning
      explicit; the module under test calls the same function internally.
    """
    calendar = Schedule(name="x", project_start=_START, tasks=()).calendar
    return datetime_to_offset(_START, target, calendar)


# A single registry of (id -> (Threshold, expected_direction, expected_value)) so
# the threshold table is asserted in one place (H-DRIFT-2 parity test below).
_THRESHOLDS = {
    "DCMA-09": (THRESHOLD_INVALID_DATES, Direction.EQ, 0.0),
    "DCMA-10": (THRESHOLD_RESOURCES, Direction.LE, 5.0),
    "DCMA-11": (THRESHOLD_MISSED_TASKS, Direction.LE, 5.0),
    "DCMA-12": (THRESHOLD_CRITICAL_PATH_TEST, Direction.EQ, 0.0),
    "DCMA-13": (THRESHOLD_CPLI, Direction.GE, 0.95),
    "DCMA-14": (THRESHOLD_BEI, Direction.GE, 0.95),
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
        # Each cited source names its own metric (M9..M14), proving no copy-paste drift.
        assert f"M{metric_id.split('-')[1].lstrip('0')}" in threshold.source, metric_id


def test_critical_path_test_delay_is_exactly_100_working_days() -> None:
    # Single source of truth for the injected delay: 100 * 480 == 48000 working min.
    assert _CRITICAL_PATH_TEST_DELAY_MIN == 100 * 480 == 48000


def test_offset_reference_values_match_calendar() -> None:
    # Pin the date<->offset reference the comments rely on (so a calendar change
    # that moved these would surface here, not silently in a downstream assert).
    assert _offset(dt.datetime(2025, 1, 6, 8)) == 0
    assert _offset(dt.datetime(2025, 1, 7, 8)) == 480
    assert _offset(dt.datetime(2025, 1, 8, 8)) == 960
    assert _offset(dt.datetime(2025, 1, 9, 8)) == 1440
    assert _offset(dt.datetime(2025, 1, 13, 8)) == 2400  # weekend skipped


# --------------------------------------------------------------------------- #
# DCMA-09 Invalid Dates (CPM-dependent)
# --------------------------------------------------------------------------- #
def test_invalid_dates_flags_three_kinds_and_spares_constrained_future_task() -> None:
    # status_date = Wed Jan8 08:00 -> status_off = 960. Four non-summary tasks:
    #   T1: actual_start Thu Jan9 (> status)            -> invalid: actual_start_after_status
    #   T2: actual_finish Thu Jan9 (> status), complete -> invalid: actual_finish_after_status
    #   T3: incomplete, no actual_start, CPM es=0 < 960  -> invalid: forecast_start_in_past
    #   T4: incomplete, no actual_start, SNET Mon Jan13  -> CPM es=2400 >= 960 -> NOT invalid
    # 3 invalid of 4 non-summary = 75% > 0 (EQ) => FAIL.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="T1",
                duration_minutes=480,
                actual_start=dt.datetime(2025, 1, 9, 8),
                percent_complete=50.0,
            ),
            Task(
                unique_id=2,
                name="T2",
                duration_minutes=480,
                actual_finish=dt.datetime(2025, 1, 9, 8),
                percent_complete=100.0,
            ),
            Task(unique_id=3, name="T3", duration_minutes=480, percent_complete=0.0),
            Task(
                unique_id=4,
                name="T4",
                duration_minutes=480,
                constraint_type=ConstraintType.SNET,
                constraint_date=dt.datetime(2025, 1, 13, 8),
            ),
        ],
        status_date=dt.datetime(2025, 1, 8, 8),
    )
    cpm = compute_cpm(schedule)
    # Cross-check the forecast term the metric reads (hand-traced es above == engine).
    assert cpm.timings[3].early_start == 0  # T3 starts at project start
    assert cpm.timings[4].early_start == 2400  # SNET Mon Jan13
    result = check_invalid_dates(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 3 / 4 * 100.0  # 75.0
    flagged = {(o.unique_id, o.detail) for o in result.offenders}
    assert flagged == {
        (1, "actual_start_after_status"),
        (2, "actual_finish_after_status"),
        (3, "forecast_start_in_past"),
    }


def test_invalid_dates_clean_schedule_passes() -> None:
    # status_date = Wed Jan8. Both tasks consistent:
    #   T1: complete, actual_finish Tue Jan7 (<= status), actual_start Mon Jan6.
    #   T2: incomplete, no actual_start, but CPM es = 480 (T1->T2 FS) which is NOT
    #       < status_off 960? 480 < 960 IS true -> would flag forecast_start_in_past.
    # To keep T2 clean we give it an SNET at Wed Jan8 (es=960, not < 960). 0 invalid
    # of 2 = 0% == threshold => PASS. (The clean half of the H-VACUOUS pair below.)
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="T1",
                duration_minutes=480,
                actual_start=dt.datetime(2025, 1, 6, 8),
                actual_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="T2",
                duration_minutes=480,
                constraint_type=ConstraintType.SNET,
                constraint_date=dt.datetime(2025, 1, 8, 8),
            ),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
        status_date=dt.datetime(2025, 1, 8, 8),
    )
    cpm = compute_cpm(schedule)
    assert cpm.timings[2].early_start == 960  # SNET floor == status_off, not < it
    result = check_invalid_dates(schedule, cpm)
    assert result.measured == 0.0
    assert result.status is MetricStatus.PASS
    assert result.offenders == ()


def test_invalid_dates_perturbation_flips_clean_task_to_invalid() -> None:
    # Take the clean PASS network and PERTURB only T2: drop its SNET so its CPM
    # early start falls to 480 (driven by T1) which is < status_off 960 -> it now
    # forecasts a start in the past. 1 of 2 = 50% => FAIL. Same data otherwise --
    # proving the check actually reads the CPM forecast (H-VACUOUS-TEST).
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="T1",
                duration_minutes=480,
                actual_start=dt.datetime(2025, 1, 6, 8),
                actual_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(unique_id=2, name="T2", duration_minutes=480),  # SNET removed
        ],
        [Relation(predecessor_id=1, successor_id=2)],
        status_date=dt.datetime(2025, 1, 8, 8),
    )
    cpm = compute_cpm(schedule)
    assert cpm.timings[2].early_start == 480  # now < status_off 960
    result = check_invalid_dates(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1 / 2 * 100.0  # 50.0
    assert {o.unique_id for o in result.offenders} == {2}


def test_invalid_dates_skipped_without_status_date() -> None:
    schedule = _sched([Task(unique_id=1, name="A", duration_minutes=480)])
    cpm = compute_cpm(schedule)
    result = check_invalid_dates(schedule, cpm)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None
    assert result.detail  # a non-empty reason, never a fabricated 0


# --------------------------------------------------------------------------- #
# DCMA-10 Resources
# --------------------------------------------------------------------------- #
def test_resources_counts_only_incomplete_with_duration_and_no_resource() -> None:
    # Denominator = incomplete non-summary tasks with duration > 0:
    #   R1: incomplete, dur 480, NO resources -> offender
    #   R2: incomplete, dur 480, has 'Alice'  -> in denom, not offender
    #   R3: incomplete, dur 0 (milestone)      -> excluded from denom
    #   R4: complete                           -> excluded from denom
    # 1 missing of 2 = 50% > 5% => FAIL.
    schedule = _sched(
        [
            Task(unique_id=1, name="R1", duration_minutes=480),
            Task(unique_id=2, name="R2", duration_minutes=480, resource_names=("Alice",)),
            Task(unique_id=3, name="R3", duration_minutes=0),
            Task(unique_id=4, name="R4", duration_minutes=480, percent_complete=100.0),
        ],
    )
    result = check_resources(schedule)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1 / 2 * 100.0  # 50.0
    assert [o.unique_id for o in result.offenders] == [1]
    assert result.offenders[0].kind == "missing_resource"


def test_resources_passes_when_all_assigned() -> None:
    # 2 incomplete tasks (dur > 0), both resourced -> 0 of 2 = 0% <= 5% => PASS.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480, resource_names=("Alice",)),
            Task(unique_id=2, name="B", duration_minutes=480, resource_names=("Bob", "Carol")),
        ],
    )
    result = check_resources(schedule)
    assert result.measured == 0.0
    assert result.status is MetricStatus.PASS
    assert result.offenders == ()


def test_resources_skipped_when_denominator_empty() -> None:
    # Only a complete task and a zero-duration milestone -> empty denominator.
    schedule = _sched(
        [
            Task(unique_id=1, name="Done", duration_minutes=480, percent_complete=100.0),
            Task(unique_id=2, name="Milestone", duration_minutes=0),
        ],
    )
    result = check_resources(schedule)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


# --------------------------------------------------------------------------- #
# DCMA-11 Missed Tasks (CPM-dependent)
# --------------------------------------------------------------------------- #
def test_missed_tasks_actual_and_forecast_both_counted() -> None:
    # Denominator = non-summary tasks with a baseline_finish.
    #   M1: complete, actual_finish Thu Jan9 > baseline Tue Jan7 => missed (actual)
    #   M2: complete, actual_finish Tue Jan7 <= baseline Thu Jan9 => on time
    #   M3: incomplete, baseline Tue Jan7 (off 480); M2->M3 FS so ef=960 > 480 => missed
    #   M4: NO baseline -> excluded from denominator
    # 2 missed of 3 baselined = 66.66...% > 5% => FAIL.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="M1",
                duration_minutes=480,
                actual_finish=dt.datetime(2025, 1, 9, 8),
                baseline_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="M2",
                duration_minutes=480,
                actual_finish=dt.datetime(2025, 1, 7, 8),
                baseline_finish=dt.datetime(2025, 1, 9, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=3,
                name="M3",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=0.0,
            ),
            Task(unique_id=4, name="M4", duration_minutes=480),
        ],
        [Relation(predecessor_id=2, successor_id=3)],
    )
    cpm = compute_cpm(schedule)
    # Cross-check the forecast term the metric reads (hand-traced above == engine).
    assert cpm.timings[3].early_finish == 960  # M2 ef 480 -> M3 es 480 ef 960
    result = check_missed_tasks(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 100.0 * 2 / 3  # 66.666...67
    flagged = {(o.unique_id, o.kind) for o in result.offenders}
    assert flagged == {(1, "missed_actual_finish"), (3, "missed_forecast_finish")}
    # The forecast offender carries the lateness in working minutes: 960 - 480 = 480.
    forecast_off = next(o for o in result.offenders if o.unique_id == 3)
    assert forecast_off.value == 480.0


def test_missed_tasks_passes_when_all_on_or_before_baseline() -> None:
    # Two baselined tasks, both finish on/before baseline:
    #   M1: complete, actual_finish Tue Jan7, baseline Wed Jan8 -> not missed
    #   M2: incomplete, baseline Fri Jan10 (off 1920); standalone ef=480 <= 1920 -> not missed
    # 0 missed of 2 = 0% <= 5% => PASS. (Clean half of the perturbation pair below.)
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="M1",
                duration_minutes=480,
                actual_finish=dt.datetime(2025, 1, 7, 8),
                baseline_finish=dt.datetime(2025, 1, 8, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="M2",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 10, 8),
                percent_complete=0.0,
            ),
        ],
    )
    cpm = compute_cpm(schedule)
    result = check_missed_tasks(schedule, cpm)
    assert result.measured == 0.0
    assert result.status is MetricStatus.PASS


def test_missed_tasks_perturbation_tightening_baseline_forces_miss() -> None:
    # PERTURB the clean case: pull M2's baseline back to Mon Jan6 (off 0). Its CPM
    # forecast finish is 480 > 0 -> now a forecast miss. 1 of 2 = 50% => FAIL.
    # Only the baseline changed, proving the forecast comparison is real.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="M1",
                duration_minutes=480,
                actual_finish=dt.datetime(2025, 1, 7, 8),
                baseline_finish=dt.datetime(2025, 1, 8, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="M2",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 6, 8),
                percent_complete=0.0,
            ),
        ],
    )
    cpm = compute_cpm(schedule)
    result = check_missed_tasks(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1 / 2 * 100.0  # 50.0
    assert {o.unique_id for o in result.offenders} == {2}


def test_missed_tasks_skipped_without_baseline() -> None:
    schedule = _sched([Task(unique_id=1, name="A", duration_minutes=480)])
    cpm = compute_cpm(schedule)
    result = check_missed_tasks(schedule, cpm)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


# --------------------------------------------------------------------------- #
# DCMA-12 Critical Path Test (perturbation pair: H-VACUOUS-TEST)
# --------------------------------------------------------------------------- #
def test_critical_path_test_passes_when_delay_flows_through() -> None:
    # Linear chain A(1)->B(2)->C(3), each 480. Forward: es 0/480/960, ef 480/960/1440;
    # project_finish 1440. critical_path = (1,2,3); min critical-with-duration = 1.
    # Inject D = 48000 into task 1: A ef 48480, B es 48480 ef 48960, C es 48960
    # ef 49440 -> new finish 49440. delta = 49440 - 1440 = 48000 == D => PASS.
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
    assert cpm.project_finish == 1440
    assert cpm.critical_path == (1, 2, 3)
    result = check_critical_path_test(schedule, cpm)
    assert result.status is MetricStatus.PASS
    assert result.measured == 0.0  # 0.0 encodes PASS (EQ-to-zero threshold)
    assert result.offenders == ()


def test_critical_path_test_fails_when_chosen_task_does_not_drive_finish() -> None:
    # PERTURBATION counterpart: a network where the smallest-id critical task is NOT
    # the finish driver, so its injected delay is (largely) absorbed.
    #   Short(1): dur 480, deadline at offset 0 -> total_float = 0 - 480 = -480 <= 0
    #             => CRITICAL, but it has NO successor and does not drive the finish.
    #   Long(2)->Long2(3): 9600 + 9600 -> Long2 ef 19200 drives project_finish.
    # critical_path = (1, 2, 3) (all total_float <= 0); min critical-with-duration = 1.
    # Inject D = 48000 into Short(1): its ef becomes 480 + 48000 = 48480, the new
    # network max early_finish (it has no successor to push), so new finish = 48480.
    # delta = 48480 - 19200 = 29280 != 48000 => FAIL. Absorbed = 48000 - 29280 = 18720.
    schedule = _sched(
        [
            Task(
                unique_id=1, name="Short", duration_minutes=480, deadline=dt.datetime(2025, 1, 6, 8)
            ),  # offset 0 -> negative float
            Task(unique_id=2, name="Long", duration_minutes=9600),
            Task(unique_id=3, name="Long2", duration_minutes=9600),
        ],
        [Relation(predecessor_id=2, successor_id=3)],
    )
    cpm = compute_cpm(schedule)
    # Confirm the fixture really makes the short task critical-but-not-driving.
    assert cpm.timings[1].total_float == -480 and cpm.timings[1].is_critical
    assert cpm.project_finish == 19200  # driven by the Long chain, not task 1
    assert cpm.critical_path == (1, 2, 3)
    result = check_critical_path_test(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1.0  # 1.0 encodes FAIL
    assert len(result.offenders) == 1
    off = result.offenders[0]
    assert off.unique_id == 1 and off.kind == "absorbed_delay_minutes"
    assert off.value == 18720.0  # 48000 injected - 29280 that flowed through


def test_critical_path_test_skipped_when_no_critical_task_with_duration() -> None:
    # A single zero-duration milestone is the only (critical) task; there is no
    # critical task with duration > 0 to perturb -> SKIPPED (never a fake verdict).
    schedule = _sched([Task(unique_id=1, name="MS", duration_minutes=0)])
    cpm = compute_cpm(schedule)
    assert cpm.critical_path == (1,)  # the milestone is critical (float 0)
    result = check_critical_path_test(schedule, cpm)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


# --------------------------------------------------------------------------- #
# DCMA-13 CPLI
# --------------------------------------------------------------------------- #
def test_cpli_on_baseline_is_exactly_one_and_passes() -> None:
    # Chain A->B->C each 480 -> project_finish (forecast_off) = 1440.
    # status_date = Tue Jan7 -> status_off = 480.
    # project baseline_finish = Thu Jan9 -> baseline_off = 1440.
    # CPLI = (1440 - 480) / (1440 - 480) = 960 / 960 = 1.0 >= 0.95 => PASS.
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
        status_date=dt.datetime(2025, 1, 7, 8),
        baseline_finish=dt.datetime(2025, 1, 9, 8),
    )
    cpm = compute_cpm(schedule)
    assert cpm.project_finish == 1440
    result = check_cpli(schedule, cpm)
    assert result.status is MetricStatus.PASS
    assert result.measured == (1440 - 480) / (1440 - 480)  # 1.0


def test_cpli_behind_schedule_is_below_threshold_and_fails() -> None:
    # Same network/forecast (1440) and status (480), but a TIGHTER project baseline
    # finish = Wed Jan8 -> baseline_off = 960.
    # CPLI = (960 - 480) / (1440 - 480) = 480 / 960 = 0.5 < 0.95 => FAIL. Only the
    # project baseline changed vs the PASS case -- the forecast came from the CPM.
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
        status_date=dt.datetime(2025, 1, 7, 8),
        baseline_finish=dt.datetime(2025, 1, 8, 8),
    )
    cpm = compute_cpm(schedule)
    result = check_cpli(schedule, cpm)
    assert result.status is MetricStatus.FAIL
    assert result.measured == (960 - 480) / (1440 - 480)  # 0.5


def test_cpli_exactly_threshold_passes() -> None:
    # Boundary: CPLI == 0.95 must PASS (GE). One task, duration 2000 -> forecast 2000.
    # status_date = project start -> status_off = 0. We need baseline_off = 1900 so
    # CPLI = 1900 / 2000 = 0.95. 1900 working minutes = 3 full days (1440) + 460 min
    # into Thu Jan9 -> 08:00 + 460 min = 15:40. (Verified via _offset below.)
    baseline = dt.datetime(2025, 1, 9, 15, 40)
    assert _offset(baseline) == 1900
    schedule = _sched(
        [Task(unique_id=1, name="A", duration_minutes=2000)],
        status_date=_START,
        baseline_finish=baseline,
    )
    cpm = compute_cpm(schedule)
    assert cpm.project_finish == 2000
    result = check_cpli(schedule, cpm)
    assert result.measured == 1900 / 2000  # 0.95
    assert result.status is MetricStatus.PASS


def test_cpli_skipped_without_status_date() -> None:
    schedule = _sched(
        [Task(unique_id=1, name="A", duration_minutes=480)],
        baseline_finish=dt.datetime(2025, 1, 9, 8),
    )
    result = check_cpli(schedule, compute_cpm(schedule))
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


def test_cpli_skipped_without_project_baseline_finish() -> None:
    schedule = _sched(
        [Task(unique_id=1, name="A", duration_minutes=480)],
        status_date=dt.datetime(2025, 1, 7, 8),
    )
    result = check_cpli(schedule, compute_cpm(schedule))
    assert result.status is MetricStatus.SKIPPED


def test_cpli_skipped_when_degenerate() -> None:
    # status_date AFTER the forecast finish: forecast_off - status_off <= 0 -> SKIP
    # (no remaining critical-path length to index; never a fabricated ratio).
    # Chain A->B each 480 -> forecast 960. status Fri Jan10 -> status_off 1920.
    # 960 - 1920 = -960 <= 0 => SKIP.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
        status_date=dt.datetime(2025, 1, 10, 8),
        baseline_finish=dt.datetime(2025, 1, 8, 8),
    )
    cpm = compute_cpm(schedule)
    assert cpm.project_finish == 960
    result = check_cpli(schedule, cpm)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


# --------------------------------------------------------------------------- #
# DCMA-14 BEI (perturbation pair: H-VACUOUS-TEST)
# --------------------------------------------------------------------------- #
def test_bei_all_due_complete_passes() -> None:
    # status_date = Wed Jan8. Two non-summary tasks, both baseline_finish <= status:
    #   T1 baseline Tue Jan7, actual_finish Tue Jan7 (complete)
    #   T2 baseline Wed Jan8, actual_finish Wed Jan8 (complete)
    # should_complete = 2, completed = 2 -> BEI = 2/2 = 1.0 >= 0.95 => PASS.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="T1",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 7, 8),
                actual_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="T2",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 8, 8),
                actual_finish=dt.datetime(2025, 1, 8, 8),
                percent_complete=100.0,
            ),
        ],
        status_date=dt.datetime(2025, 1, 8, 8),
    )
    result = check_bei(schedule)
    assert result.status is MetricStatus.PASS
    assert result.measured == 2 / 2  # 1.0


def test_bei_perturbation_one_incomplete_due_task_fails() -> None:
    # PERTURB the all-complete case: clear T2's actual_finish (and drop its
    # percent_complete) so it is no longer complete. should_complete is unchanged
    # at 2 (both are still baselined <= status); completed drops to 1 -> BEI =
    # 1/2 = 0.5 < 0.95 => FAIL. Only T2's actual_finish changed -- proving BEI
    # actually counts completed-vs-due (H-VACUOUS-TEST).
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="T1",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 7, 8),
                actual_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="T2",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 8, 8),
                actual_finish=None,
                percent_complete=50.0,
            ),
        ],
        status_date=dt.datetime(2025, 1, 8, 8),
    )
    result = check_bei(schedule)
    assert result.status is MetricStatus.FAIL
    assert result.measured == 1 / 2  # 0.5


def test_bei_excludes_tasks_baselined_after_status_date() -> None:
    # status_date = Tue Jan7. Only T1 (baseline Tue Jan7 <= status) is "due"; T2
    # (baseline Thu Jan9 > status) is NOT due and excluded from BOTH numerator and
    # denominator. T1 is complete -> should_complete = 1, completed = 1 -> BEI = 1.0.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="T1",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 7, 8),
                actual_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="T2",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 9, 8),
                percent_complete=0.0,
            ),
        ],
        status_date=dt.datetime(2025, 1, 7, 8),
    )
    result = check_bei(schedule)
    assert result.measured == 1 / 1  # 1.0; T2 not yet due
    assert result.status is MetricStatus.PASS


def test_bei_exactly_threshold_passes() -> None:
    # Boundary: BEI == 0.95 must PASS (GE). 20 tasks all baselined <= status; 19
    # complete, 1 incomplete -> 19/20 = 0.95. status_date = Mon Jan20.
    tasks = [
        Task(
            unique_id=i,
            name=f"T{i}",
            duration_minutes=480,
            baseline_finish=dt.datetime(2025, 1, 8, 8),  # all due by status
            actual_finish=(dt.datetime(2025, 1, 7, 8) if i <= 19 else None),
            percent_complete=(100.0 if i <= 19 else 0.0),
        )
        for i in range(1, 21)
    ]
    schedule = _sched(tasks, status_date=dt.datetime(2025, 1, 20, 8))
    result = check_bei(schedule)
    assert result.measured == 19 / 20  # 0.95
    assert result.status is MetricStatus.PASS


def test_bei_skipped_without_status_date() -> None:
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 7, 8),
            )
        ]
    )
    result = check_bei(schedule)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


def test_bei_skipped_when_nothing_due_by_status() -> None:
    # status_date = Mon Jan6 (offset 0). The only task is baselined Fri Jan10 (> status)
    # so should_complete == 0 -> SKIPPED (never a fabricated ratio).
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 10, 8),
            )
        ],
        status_date=dt.datetime(2025, 1, 6, 8),
    )
    result = check_bei(schedule)
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None


# --------------------------------------------------------------------------- #
# run_progress_checks orchestration + CPM-skip handling
# --------------------------------------------------------------------------- #
def _full_schedule() -> Schedule:
    # A small but fully-populated schedule so every check can actually run:
    # chain A->B->C each 480; status Wed Jan8; project baseline Thu Jan9; A complete
    # on its baseline, B/C baselined and resourced.
    return _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                resource_names=("Alice",),
                actual_start=dt.datetime(2025, 1, 6, 8),
                actual_finish=dt.datetime(2025, 1, 7, 8),
                baseline_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(
                unique_id=2,
                name="B",
                duration_minutes=480,
                resource_names=("Bob",),
                baseline_finish=dt.datetime(2025, 1, 9, 8),
                percent_complete=0.0,
            ),
            Task(
                unique_id=3,
                name="C",
                duration_minutes=480,
                resource_names=("Carol",),
                baseline_finish=dt.datetime(2025, 1, 13, 8),
                percent_complete=0.0,
            ),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=3),
        ],
        status_date=dt.datetime(2025, 1, 8, 8),
        baseline_finish=dt.datetime(2025, 1, 9, 8),
    )


def test_run_progress_checks_returns_six_in_id_order_with_sources() -> None:
    results = run_progress_checks(_full_schedule())
    ids = [r.metric_id for r in results]
    # Ids are zero-padded to two digits (DCMA-09 .. DCMA-14), in ascending order.
    assert ids == [f"DCMA-{i:02d}" for i in range(9, 15)]
    # Every non-skipped result cites a non-empty source (a skip carries none by
    # contract). With the fully-populated fixture, all six execute.
    for r in results:
        if r.status is not MetricStatus.SKIPPED:
            assert r.source, f"{r.metric_id} returned an empty source"
            assert r.is_extension is False  # all six are reference-tool checks


def test_run_progress_checks_skips_cpm_dependent_checks_on_cycle() -> None:
    # A 2-task cycle makes compute_cpm raise CPMError. The CPM-dependent checks
    # (DCMA-09, 11, 12, 13) must become SKIPPED with the CPM error surfaced; the
    # two needing no CPM (DCMA-10 Resources, DCMA-14 BEI) must still run.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                baseline_finish=dt.datetime(2025, 1, 8, 8),
                actual_finish=dt.datetime(2025, 1, 7, 8),
                percent_complete=100.0,
            ),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=1),  # back-edge => cycle
        ],
        status_date=dt.datetime(2025, 1, 8, 8),
        baseline_finish=dt.datetime(2025, 1, 9, 8),
    )
    # Sanity: confirm the engine truly raises (so the skip path is meaningful).
    raised = False
    try:
        compute_cpm(schedule)
    except CPMError:
        raised = True
    assert raised, "fixture must make compute_cpm raise for the skip path to be meaningful"

    results = {r.metric_id: r for r in run_progress_checks(schedule)}
    for cpm_dependent in ("DCMA-09", "DCMA-11", "DCMA-12", "DCMA-13"):
        assert results[cpm_dependent].status is MetricStatus.SKIPPED, cpm_dependent
        assert "CPM" in results[cpm_dependent].detail  # error surfaced, not swallowed
    # The CPM-free checks still produced a real verdict.
    assert results["DCMA-10"].status in (MetricStatus.PASS, MetricStatus.FAIL)
    # B is incomplete, dur > 0, no resource -> 1 of 1 missing => FAIL.
    assert results["DCMA-10"].status is MetricStatus.FAIL
    # 1 due baselined task (A, baseline <= status) and it is complete -> BEI 1.0 PASS.
    assert results["DCMA-14"].status is MetricStatus.PASS


def test_run_progress_checks_reuses_supplied_cpm_result() -> None:
    # When a CPMResult is supplied, run_* must reuse it (the CPM-dependent checks
    # run rather than skip).
    schedule = _full_schedule()
    cpm = compute_cpm(schedule)
    results = {r.metric_id: r for r in run_progress_checks(schedule, cpm)}
    # All four CPM-dependent checks ran (not skipped).
    for cpm_dependent in ("DCMA-09", "DCMA-11", "DCMA-12", "DCMA-13"):
        assert results[cpm_dependent].status is not MetricStatus.SKIPPED, cpm_dependent
