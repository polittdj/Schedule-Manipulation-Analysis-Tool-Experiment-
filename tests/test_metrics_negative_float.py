"""DCMA Metric 8 (Negative Float) — known-answer tests. 8h/day -> 1 day = 480 min."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.cpm import compute_cpm
from app.exceptions import MetricError
from app.metrics import run_negative_float
from app.models import Severity
from tests.conftest import make_relation, make_schedule, make_task

DAY = 480


def test_negative_float_flagged_when_deadline_missed() -> None:
    tasks = (
        make_task(1, duration_minutes=2 * DAY),
        make_task(2, duration_minutes=3 * DAY, deadline=datetime(2026, 1, 6, 16, 0)),
    )
    schedule = make_schedule(tasks=tasks, relations=(make_relation(1, 2),))
    result = run_negative_float(schedule, compute_cpm(schedule))
    assert result.metric_id == 8
    assert (result.numerator, result.denominator) == (2, 2)
    assert {o.unique_id for o in result.offenders} == {1, 2}
    assert result.offenders[0].value == -3.0  # working days
    assert result.severity == Severity.FAIL  # threshold is 0% — any negative float fails


def test_negative_float_clean_schedule_passes() -> None:
    tasks = tuple(make_task(i, duration_minutes=DAY) for i in range(1, 4))
    relations = tuple(make_relation(i, i + 1) for i in range(1, 3))
    schedule = make_schedule(tasks=tasks, relations=relations)
    result = run_negative_float(schedule, compute_cpm(schedule))
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_negative_float_empty_raises() -> None:
    cpm = compute_cpm(make_schedule(tasks=(make_task(1),), relations=()))
    with pytest.raises(MetricError):
        run_negative_float(make_schedule(tasks=(), relations=()), cpm)
