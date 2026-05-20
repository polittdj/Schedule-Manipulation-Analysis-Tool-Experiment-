"""DCMA Metrics 6 (High Duration) and 7 (High Float) — known-answer tests.

High bar = 44 working days; threshold <= 5% of tasks. 8h/day -> 1 day = 480 min.
"""

from __future__ import annotations

import pytest

from app.cpm import compute_cpm
from app.exceptions import MetricError
from app.metrics import run_high_duration, run_high_float
from app.models import Severity
from tests.conftest import make_relation, make_schedule, make_task

DAY = 480


def test_high_duration_flags_tasks_over_44_days() -> None:
    tasks = (
        make_task(1, duration_minutes=45 * DAY),
        make_task(2, duration_minutes=44 * DAY),  # exactly 44 is NOT > 44
        make_task(3, duration_minutes=10 * DAY),
    )
    result = run_high_duration(make_schedule(tasks=tasks, relations=()))
    assert result.metric_id == 8
    assert (result.numerator, result.denominator) == (1, 3)
    assert result.offenders[0].unique_id == 1
    assert result.offenders[0].value == 45.0
    assert result.severity == Severity.FAIL


def test_high_duration_all_short_passes() -> None:
    tasks = tuple(make_task(i, duration_minutes=5 * DAY) for i in range(1, 4))
    result = run_high_duration(make_schedule(tasks=tasks, relations=()))
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_high_duration_empty_raises() -> None:
    with pytest.raises(MetricError):
        run_high_duration(make_schedule(tasks=(), relations=()))


def test_high_float_flags_float_over_44_days() -> None:
    # task 1 (1d) and task 2 (50d) both feed task 3; task 1 gains ~49 days of float.
    tasks = (
        make_task(1, duration_minutes=1 * DAY),
        make_task(2, duration_minutes=50 * DAY),
        make_task(3, duration_minutes=1 * DAY),
    )
    relations = (make_relation(1, 3), make_relation(2, 3))
    schedule = make_schedule(tasks=tasks, relations=relations)
    result = run_high_float(schedule, compute_cpm(schedule))
    assert result.metric_id == 6
    assert (result.numerator, result.denominator) == (1, 3)
    assert result.offenders[0].unique_id == 1
    assert result.offenders[0].value == 49.0
    assert result.severity == Severity.FAIL


def test_high_float_critical_chain_passes() -> None:
    tasks = tuple(make_task(i, duration_minutes=DAY) for i in range(1, 4))
    relations = tuple(make_relation(i, i + 1) for i in range(1, 3))
    schedule = make_schedule(tasks=tasks, relations=relations)
    result = run_high_float(schedule, compute_cpm(schedule))
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_high_float_empty_schedule_raises() -> None:
    # The metric guards on its own schedule's tasks before touching the CPM result.
    cpm = compute_cpm(make_schedule(tasks=(make_task(1),), relations=()))
    with pytest.raises(MetricError):
        run_high_float(make_schedule(tasks=(), relations=()), cpm)
