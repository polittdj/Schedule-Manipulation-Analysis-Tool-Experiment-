"""DCMA Metrics 9 (Invalid Dates), 10 (Resources), 11 (Missed Tasks) — known-answer tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions import MetricError
from app.metrics import run_invalid_dates, run_missed_tasks, run_resources
from app.models import Severity
from tests.conftest import make_schedule, make_task

STATUS = datetime(2026, 2, 1, 8, 0)
DAY = 480


# --- Metric 9: Invalid Dates -----------------------------------------------------------


def test_invalid_dates_flags_future_actuals_and_inconsistent_progress() -> None:
    tasks = (
        make_task(
            1,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 10, 16, 0),  # before status -> OK
        ),
        make_task(
            2,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 3, 1, 8, 0),  # after status -> invalid
        ),
        make_task(3, percent_complete=100),  # claims complete but no actual_finish -> invalid
    )
    result = run_invalid_dates(make_schedule(tasks=tasks, relations=(), status_date=STATUS))
    assert result.metric_id == 9
    assert (result.numerator, result.denominator) == (2, 3)
    assert {o.unique_id for o in result.offenders} == {2, 3}
    assert result.severity == Severity.FAIL


def test_invalid_dates_clean_passes() -> None:
    tasks = (
        make_task(
            1,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 10, 16, 0),
        ),
        make_task(2, percent_complete=0),  # not started, no actuals -> consistent
    )
    result = run_invalid_dates(make_schedule(tasks=tasks, relations=(), status_date=STATUS))
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_invalid_dates_requires_status_date() -> None:
    with pytest.raises(MetricError):
        run_invalid_dates(make_schedule(tasks=(make_task(1),), relations=()))


# --- Metric 10: Resources --------------------------------------------------------------


def test_resources_flags_detail_tasks_without_resources() -> None:
    tasks = (
        make_task(1, duration_minutes=DAY, resource_names=("Alice",)),
        make_task(2, duration_minutes=DAY),  # detail, no resource -> offender
        make_task(3, duration_minutes=0),  # milestone -> excluded from denominator
    )
    result = run_resources(make_schedule(tasks=tasks, relations=()))
    assert result.metric_id == 10
    assert (result.numerator, result.denominator) == (1, 2)  # task 3 milestone excluded
    assert {o.unique_id for o in result.offenders} == {2}
    assert result.severity == Severity.FAIL


def test_resources_all_assigned_passes() -> None:
    tasks = tuple(make_task(i, duration_minutes=DAY, resource_names=("crew",)) for i in range(1, 4))
    result = run_resources(make_schedule(tasks=tasks, relations=()))
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_resources_requires_a_detail_task() -> None:
    with pytest.raises(MetricError):
        run_resources(make_schedule(tasks=(make_task(1, duration_minutes=0),), relations=()))


# --- Metric 11: Missed Tasks -----------------------------------------------------------


def test_missed_tasks_flags_late_and_unfinished() -> None:
    due = datetime(2026, 1, 15, 16, 0)  # baseline finish before the data date
    tasks = (
        make_task(
            1,
            baseline_finish=due,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 14, 16, 0),  # on time -> OK
        ),
        make_task(
            2,
            baseline_finish=due,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 20, 16, 0),  # late -> missed
        ),
        make_task(3, baseline_finish=due),  # due but unfinished -> missed
        make_task(4, baseline_finish=datetime(2026, 3, 1, 16, 0)),  # not due yet -> excluded
    )
    result = run_missed_tasks(make_schedule(tasks=tasks, relations=(), status_date=STATUS))
    assert result.metric_id == 11
    assert (result.numerator, result.denominator) == (2, 3)  # task 4 not due
    assert {o.unique_id for o in result.offenders} == {2, 3}
    assert result.severity == Severity.FAIL


def test_missed_tasks_all_on_time_passes() -> None:
    due = datetime(2026, 1, 15, 16, 0)
    tasks = (
        make_task(
            1,
            baseline_finish=due,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 14, 16, 0),
        ),
    )
    result = run_missed_tasks(make_schedule(tasks=tasks, relations=(), status_date=STATUS))
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_missed_tasks_requires_status_and_due_tasks() -> None:
    with pytest.raises(MetricError):
        run_missed_tasks(make_schedule(tasks=(make_task(1),), relations=()))  # no status_date
    with pytest.raises(MetricError):  # status set but nothing due by then
        run_missed_tasks(make_schedule(tasks=(make_task(1),), relations=(), status_date=STATUS))
