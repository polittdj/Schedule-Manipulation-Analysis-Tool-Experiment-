"""DCMA 14-Point Assessment -- the PROGRESS checks (Metrics 9-14).

This module implements the six DCMA-14 checks that depend on the schedule's
*tracking / progress* fields (actual dates, percent-complete, baseline finish,
status date) plus the CPM forecast. The eight structure-only checks (Metrics
1-8) live in :mod:`schedule_forensics.dcma_checks` -- one module per dispatch
(CLAUDE.md commandment 4); this module mirrors that one's style exactly.

The six checks here, with their canonical DCMA thresholds:

  * DCMA-09 Invalid Dates       -- == 0% of tasks have a date inconsistent with the status date
  * DCMA-10 Resources           -- <= 5% of incomplete tasks (with duration) lack a resource
  * DCMA-11 Missed Tasks        -- <= 5% of baselined tasks finish (or forecast) past baseline
  * DCMA-12 Critical Path Test  -- PASS iff an injected delay on the critical path flows to finish
  * DCMA-13 CPLI                -- >= 0.95 Critical Path Length Index
  * DCMA-14 BEI                 -- >= 0.95 Baseline Execution Index

Source / parity honesty (LAW 2): these checks and threshold *values* are the
canonical DCMA 14-Point Assessment numbers (REFERENCES.md keys ``DCMA-EDWARDS``
/ ``DCMA-WINTER``). The threshold values are well-known and canonical, but the
exact page anchors are **source-pending** until those documents land in
``docs/sources/`` -- every ``Threshold.source`` below says so explicitly rather
than inventing a page number (H-FICTIONAL-RULE). None of these six is a
tool-original extension; they are reference-tool checks and are NOT flagged
``is_extension``.

Single source of truth (H-DRIFT-2): each threshold is a module-level
:class:`~schedule_forensics.metrics_common.Threshold` constant; the corresponding
check reads that constant and nothing else. A parametrized test pins value,
direction, and a non-empty cited source for every metric id.

Units / axis (matches :mod:`schedule_forensics.cpm`): the internal time axis is
INTEGER WORKING MINUTES measured from ``Schedule.project_start`` (480 working
minutes == one 8-hour day). Wall-clock dates (status date, baseline finish) are
mapped onto that axis with
:func:`~schedule_forensics.cpm.datetime_to_offset` so date comparisons line up
exactly with CPM offsets.

Scope conventions (CLAUDE.md): every check operates on NON-SUMMARY tasks only
(summaries are date rollups, absent from
:class:`~schedule_forensics.cpm.CPMResult` timings). "Incomplete" means
``percent_complete < 100``. A check whose required data is absent (no status
date, no baseline, no CPM, an empty denominator) returns SKIPPED with a reason
-- it never divides by zero and never reports a fabricated ``0`` (H-DRIFT-1).
"""

from __future__ import annotations

from schedule_forensics.cpm import (
    CPMError,
    CPMResult,
    compute_cpm,
    datetime_to_offset,
)
from schedule_forensics.metrics_common import (
    Direction,
    MetricResult,
    Offender,
    Threshold,
    evaluate,
    skipped,
)
from schedule_forensics.schemas import Schedule, Task

# DCMA-12 injects a large delay on the chosen critical task and re-runs the CPM;
# if the network is truly driven through that task, the injected delay flows
# straight to the project finish. 100 working days (100 * 480) is well clear of
# any incidental float in a sane test/forensic network. (DCMA-EDWARDS M12.)
_WORKING_MINUTES_PER_DAY = 480
_CRITICAL_PATH_TEST_DELAY_MIN = 100 * _WORKING_MINUTES_PER_DAY  # 48000

# --- thresholds: defined ONCE here, each cited; checks read these constants ---
# The values are the canonical DCMA 14-Point numbers; page anchors are pending
# (the DCMA-EDWARDS / DCMA-WINTER PDFs are not yet in docs/sources/).
_SRC_M9 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M9 (Invalid Dates); page-anchor source-pending"
_SRC_M10 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M10 (Resources); page-anchor source-pending"
_SRC_M11 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M11 (Missed Tasks); page-anchor source-pending"
_SRC_M12 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M12 (Critical Path Test); page-anchor source-pending"
_SRC_M13 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M13 (CPLI); page-anchor source-pending"
_SRC_M14 = "DCMA-EDWARDS / DCMA-WINTER 14-pt M14 (BEI); page-anchor source-pending"

THRESHOLD_INVALID_DATES = Threshold(value=0.0, direction=Direction.EQ, source=_SRC_M9)
THRESHOLD_RESOURCES = Threshold(value=5.0, direction=Direction.LE, source=_SRC_M10)
THRESHOLD_MISSED_TASKS = Threshold(value=5.0, direction=Direction.LE, source=_SRC_M11)
# DCMA-12 is a pass/fail diagnostic, not a ratio: measured 0.0 == passing, 1.0 ==
# failing, with an EQ-to-zero threshold so ``evaluate`` yields PASS exactly when
# the injected delay flows through (measured 0.0).
THRESHOLD_CRITICAL_PATH_TEST = Threshold(value=0.0, direction=Direction.EQ, source=_SRC_M12)
THRESHOLD_CPLI = Threshold(value=0.95, direction=Direction.GE, source=_SRC_M13)
THRESHOLD_BEI = Threshold(value=0.95, direction=Direction.GE, source=_SRC_M14)


def _non_summary(schedule: Schedule) -> list[Task]:
    """Real activities only -- summaries are rollups (absent from CPM timings)."""
    return [t for t in schedule.tasks if not t.is_summary]


def _is_incomplete(task: Task) -> bool:
    """DCMA "incomplete" task: not yet 100% complete (default 0.0 => incomplete)."""
    return task.percent_complete < 100.0


def _pct(count: int, total: int) -> float:
    """Percentage in 0..100 as a float. Caller guarantees ``total > 0``."""
    return 100.0 * count / total


def check_invalid_dates(schedule: Schedule, result: CPMResult) -> MetricResult:
    """DCMA-09: % of non-summary tasks whose dates are inconsistent with the status date.

    Requires both a ``status_date`` and a CPM result (the forecast term). A
    non-summary task is INVALID if ANY of:

      * ``actual_start`` is after the status date (work logged in the future), OR
      * ``actual_finish`` is after the status date, OR
      * it is incomplete (``percent_complete < 100``) with NO ``actual_start`` and
        its CPM early start is before the status-date offset -- i.e. the network
        forecasts it to have already started, yet it carries no actual start
        ("forecast in the past").

    ``measured`` is the percentage of non-summary tasks that are invalid; the
    threshold is ``== 0`` (EQ). A task absent from the CPM timings cannot supply
    the forecast term and is judged on its actual-date terms only. (DCMA-EDWARDS
    M9.)
    """
    if schedule.status_date is None:
        return skipped("DCMA-09", "Invalid Dates", "schedule has no status_date")
    tasks = _non_summary(schedule)
    if not tasks:
        return skipped("DCMA-09", "Invalid Dates", "schedule has no non-summary tasks")

    status = schedule.status_date
    status_off = datetime_to_offset(schedule.project_start, status, schedule.calendar)

    offenders: list[Offender] = []
    for task in tasks:
        reasons: list[str] = []
        if task.actual_start is not None and task.actual_start > status:
            reasons.append("actual_start_after_status")
        if task.actual_finish is not None and task.actual_finish > status:
            reasons.append("actual_finish_after_status")
        timing = result.timings.get(task.unique_id)
        if (
            _is_incomplete(task)
            and task.actual_start is None
            and timing is not None
            and timing.early_start < status_off
        ):
            reasons.append("forecast_start_in_past")
        if reasons:
            offenders.append(
                Offender(
                    unique_id=task.unique_id,
                    kind="invalid_date",
                    value=1.0,
                    detail=";".join(reasons),
                )
            )

    measured = _pct(len(offenders), len(tasks))
    detail = (
        f"{len(offenders)} of {len(tasks)} non-summary tasks have a date inconsistent "
        f"with the status date {status.date().isoformat()}"
    )
    return evaluate(
        "DCMA-09",
        "Invalid Dates",
        measured,
        THRESHOLD_INVALID_DATES,
        offenders=tuple(offenders),
        detail=detail,
    )


def check_resources(schedule: Schedule) -> MetricResult:
    """DCMA-10: % of incomplete non-summary tasks (with duration) that lack a resource.

    The denominator is the INCOMPLETE non-summary tasks with
    ``duration_minutes > 0`` (a zero-duration milestone carries no work and so
    needs no resource; completed work needs no further assignment). ``measured``
    is the share of those whose ``resource_names`` is empty; the threshold is
    ``<= 5%``. Needs no CPM. SKIPPED when the denominator would be zero
    (H-DRIFT-1 -- never a fabricated 0%). (DCMA-EDWARDS M10.)
    """
    candidates = [t for t in _non_summary(schedule) if _is_incomplete(t) and t.duration_minutes > 0]
    if not candidates:
        return skipped(
            "DCMA-10",
            "Resources",
            "no incomplete non-summary tasks with duration > 0",
        )

    offenders = tuple(
        Offender(unique_id=t.unique_id, kind="missing_resource", value=1.0, detail=t.name)
        for t in candidates
        if not t.resource_names
    )
    measured = _pct(len(offenders), len(candidates))
    detail = (
        f"{len(offenders)} of {len(candidates)} incomplete non-summary tasks "
        f"(duration > 0) have no assigned resource"
    )
    return evaluate(
        "DCMA-10",
        "Resources",
        measured,
        THRESHOLD_RESOURCES,
        offenders=offenders,
        detail=detail,
    )


def check_missed_tasks(schedule: Schedule, result: CPMResult) -> MetricResult:
    """DCMA-11: % of baselined non-summary tasks that finished (or forecast) past baseline.

    The denominator is the non-summary tasks carrying a ``baseline_finish``. A
    task is "missed" if:

      * it is COMPLETE (``actual_finish`` set) and ``actual_finish`` is after its
        ``baseline_finish``, OR
      * it is INCOMPLETE and its CPM forecast finish is past the baseline --
        ``early_finish > datetime_to_offset(start, baseline_finish, calendar)``.

    The incomplete case needs the CPM forecast, so this check requires a CPM
    result (skip-on-CPMError handled by :func:`run_progress_checks`). An
    incomplete baselined task absent from the CPM timings has no forecast term and
    cannot be judged "missed" on that basis. ``measured`` is a percentage; the
    threshold is ``<= 5%``. SKIPPED when no task carries a baseline.
    (DCMA-EDWARDS M11.)
    """
    baselined = [t for t in _non_summary(schedule) if t.baseline_finish is not None]
    if not baselined:
        return skipped("DCMA-11", "Missed Tasks", "no non-summary tasks carry a baseline_finish")

    offenders: list[Offender] = []
    for task in baselined:
        baseline = task.baseline_finish
        assert baseline is not None  # filtered above; for the type checker
        if task.actual_finish is not None:
            if task.actual_finish > baseline:
                offenders.append(
                    Offender(
                        unique_id=task.unique_id,
                        kind="missed_actual_finish",
                        value=1.0,
                        detail=f"finished {task.actual_finish.date().isoformat()} > baseline "
                        f"{baseline.date().isoformat()}",
                    )
                )
            continue
        timing = result.timings.get(task.unique_id)
        if timing is None:
            continue
        baseline_off = datetime_to_offset(schedule.project_start, baseline, schedule.calendar)
        if timing.early_finish > baseline_off:
            offenders.append(
                Offender(
                    unique_id=task.unique_id,
                    kind="missed_forecast_finish",
                    value=float(timing.early_finish - baseline_off),
                    detail=f"forecast finish offset {timing.early_finish} > baseline offset "
                    f"{baseline_off}",
                )
            )

    measured = _pct(len(offenders), len(baselined))
    detail = (
        f"{len(offenders)} of {len(baselined)} baselined non-summary tasks "
        f"finished or forecast to finish past baseline"
    )
    return evaluate(
        "DCMA-11",
        "Missed Tasks",
        measured,
        THRESHOLD_MISSED_TASKS,
        offenders=tuple(offenders),
        detail=detail,
    )


def check_critical_path_test(schedule: Schedule, result: CPMResult) -> MetricResult:
    """DCMA-12: a structural test that the critical path is real (pass/fail diagnostic).

    Method: choose the critical-path task (a member of ``result.critical_path``)
    with ``duration_minutes > 0`` and the smallest ``unique_id``; build a
    ``model_copy`` of the schedule that adds a large delay
    ``D = _CRITICAL_PATH_TEST_DELAY_MIN`` (100 working days) to that task's
    duration; re-run :func:`~schedule_forensics.cpm.compute_cpm`. The test PASSES
    iff ``new.project_finish - old.project_finish == D`` -- the injected delay
    flowed entirely through to the project finish, proving the chain truly drives
    the network. If the delay is absorbed (the task had parallel slack), the
    finish moves by less than ``D`` and the test FAILS.

    Reported as ``measured`` 0.0 (PASS) vs 1.0 (FAIL) against an EQ-to-zero
    threshold, so ``MetricResult.status`` is PASS exactly when the test passes.
    SKIPPED if there is no critical task with duration > 0, or if the re-run
    raises ``CPMError``. (DCMA-EDWARDS M12.)
    """
    # Critical-path ids come from the CPM and are non-summary tasks present in the
    # timings by construction; require duration > 0 so the injected delay has a
    # task to lengthen (a zero-duration milestone cannot carry a duration delay).
    by_id = {t.unique_id: t for t in schedule.tasks}
    critical_with_duration = [
        tid
        for tid in result.critical_path
        if tid in by_id and by_id[tid].duration_minutes > 0 and not by_id[tid].is_summary
    ]
    if not critical_with_duration:
        return skipped(
            "DCMA-12",
            "Critical Path Test",
            "no critical-path task with duration > 0 to perturb",
        )

    target_id = min(critical_with_duration)
    target = by_id[target_id]
    delayed_task = target.model_copy(
        update={"duration_minutes": target.duration_minutes + _CRITICAL_PATH_TEST_DELAY_MIN}
    )
    new_tasks = tuple(delayed_task if t.unique_id == target_id else t for t in schedule.tasks)
    perturbed = schedule.model_copy(update={"tasks": new_tasks})

    try:
        new_result = compute_cpm(perturbed)
    except CPMError as exc:
        return skipped(
            "DCMA-12",
            "Critical Path Test",
            f"CPM unavailable on the perturbed network: {exc}",
        )

    finish_delta = new_result.project_finish - result.project_finish
    passed = finish_delta == _CRITICAL_PATH_TEST_DELAY_MIN
    measured = 0.0 if passed else 1.0
    offenders = (
        ()
        if passed
        else (
            Offender(
                unique_id=target_id,
                kind="absorbed_delay_minutes",
                value=float(_CRITICAL_PATH_TEST_DELAY_MIN - finish_delta),
                detail=f"injected {_CRITICAL_PATH_TEST_DELAY_MIN} min on task {target_id}; "
                f"finish moved only {finish_delta} min",
            ),
        )
    )
    detail = (
        f"injected a {_CRITICAL_PATH_TEST_DELAY_MIN}-min delay on critical task "
        f"{target_id}; project finish moved {finish_delta} min "
        f"({'flowed through -- PASS' if passed else 'absorbed -- FAIL'})"
    )
    return evaluate(
        "DCMA-12",
        "Critical Path Test",
        measured,
        THRESHOLD_CRITICAL_PATH_TEST,
        offenders=offenders,
        detail=detail,
    )


def check_cpli(schedule: Schedule, result: CPMResult) -> MetricResult:
    """DCMA-13: Critical Path Length Index (CPLI), threshold >= 0.95.

    Requires a ``status_date``, a project ``baseline_finish``, and a CPM result.
    On the working-minute axis (offsets from ``project_start``)::

        status_off   = datetime_to_offset(start, status_date, calendar)
        baseline_off = datetime_to_offset(start, project_baseline_finish, calendar)
        forecast_off = result.project_finish
        CPLI = (baseline_off - status_off) / (forecast_off - status_off)

    CPLI is "remaining baseline duration" over "remaining forecast duration": at
    1.0 the project is exactly on its baseline critical-path length; below it the
    forecast critical path is longer than the baseline allowed. SKIPPED if
    ``forecast_off - status_off <= 0`` (degenerate -- no remaining critical-path
    length to index against; never a fabricated ratio). ``measured`` is the CPLI
    ratio. (DCMA-EDWARDS M13.)
    """
    if schedule.status_date is None:
        return skipped("DCMA-13", "CPLI", "schedule has no status_date")
    if schedule.baseline_finish is None:
        return skipped("DCMA-13", "CPLI", "schedule has no project baseline_finish")

    status_off = datetime_to_offset(schedule.project_start, schedule.status_date, schedule.calendar)
    baseline_off = datetime_to_offset(
        schedule.project_start, schedule.baseline_finish, schedule.calendar
    )
    forecast_off = result.project_finish
    remaining_forecast = forecast_off - status_off
    if remaining_forecast <= 0:
        return skipped(
            "DCMA-13",
            "CPLI",
            f"degenerate CPLI: forecast finish offset {forecast_off} <= status offset "
            f"{status_off} (no remaining critical-path length)",
        )

    cpli = (baseline_off - status_off) / remaining_forecast
    detail = (
        f"CPLI = (baseline {baseline_off} - status {status_off}) / "
        f"(forecast {forecast_off} - status {status_off}) = {cpli}"
    )
    return evaluate("DCMA-13", "CPLI", cpli, THRESHOLD_CPLI, detail=detail)


def check_bei(schedule: Schedule) -> MetricResult:
    """DCMA-14: Baseline Execution Index (BEI), threshold >= 0.95.

    Standard count-based BEI. Requires a ``status_date``::

        should_complete = # of non-summary tasks with a baseline_finish <= status_date
        completed       = # of THOSE tasks that are actually complete (actual_finish set)
        BEI             = completed / should_complete

    BEI measures throughput against the baseline plan: at 1.0 the project has
    completed exactly as many tasks as the baseline said should be done by now.
    "Complete" here is ``actual_finish is not None`` (a finished task carries an
    actual finish), independent of ``percent_complete``. SKIPPED when
    ``should_complete == 0`` (nothing was baselined to be done by the status date
    -- never a fabricated ratio). Needs no CPM. ``measured`` is the BEI ratio.
    (DCMA-EDWARDS M14.)
    """
    if schedule.status_date is None:
        return skipped("DCMA-14", "BEI", "schedule has no status_date")

    status = schedule.status_date
    due = [
        t
        for t in _non_summary(schedule)
        if t.baseline_finish is not None and t.baseline_finish <= status
    ]
    should_complete = len(due)
    if should_complete == 0:
        return skipped(
            "DCMA-14",
            "BEI",
            f"no baselined non-summary tasks were due by the status date "
            f"{status.date().isoformat()}",
        )

    completed = sum(1 for t in due if t.actual_finish is not None)
    bei = completed / should_complete
    detail = (
        f"BEI = completed {completed} / should-complete {should_complete} "
        f"(baseline finish <= {status.date().isoformat()}) = {bei}"
    )
    return evaluate("DCMA-14", "BEI", bei, THRESHOLD_BEI, detail=detail)


def run_progress_checks(
    schedule: Schedule, result: CPMResult | None = None
) -> tuple[MetricResult, ...]:
    """Run all six progress DCMA-14 checks, returned in id order DCMA-09..14.

    The CPM is computed once (reusing ``result`` if supplied). If the CPM cannot
    be computed -- a logic cycle, or a deferred constraint (ALAP/MSO/MFO) -- the
    CPM-dependent checks (DCMA-09 Invalid Dates, DCMA-11 Missed Tasks, DCMA-12
    Critical Path Test, DCMA-13 CPLI) become SKIPPED with the CPM's error message
    as the reason; the two checks that need no CPM (DCMA-10 Resources, DCMA-14
    BEI) still run. The CPM error is never swallowed silently: its message is
    surfaced in the skip reason.
    """
    cpm: CPMResult | None = result
    cpm_error: str | None = None
    if cpm is None:
        try:
            cpm = compute_cpm(schedule)
        except CPMError as exc:
            cpm_error = str(exc)

    if cpm is not None:
        invalid_dates = check_invalid_dates(schedule, cpm)
        missed_tasks = check_missed_tasks(schedule, cpm)
        critical_path_test = check_critical_path_test(schedule, cpm)
        cpli = check_cpli(schedule, cpm)
    else:
        reason = f"CPM unavailable: {cpm_error}"
        invalid_dates = skipped("DCMA-09", "Invalid Dates", reason)
        missed_tasks = skipped("DCMA-11", "Missed Tasks", reason)
        critical_path_test = skipped("DCMA-12", "Critical Path Test", reason)
        cpli = skipped("DCMA-13", "CPLI", reason)

    return (
        invalid_dates,
        check_resources(schedule),
        missed_tasks,
        critical_path_test,
        cpli,
        check_bei(schedule),
    )
