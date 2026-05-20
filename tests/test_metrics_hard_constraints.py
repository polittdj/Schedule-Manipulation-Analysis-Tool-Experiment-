"""DCMA Metric 5 (Hard Constraints) — known-answer tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions import MetricError
from app.metrics import run_hard_constraints
from app.models import ConstraintType, Severity
from tests.conftest import make_schedule, make_task

DATE = datetime(2026, 1, 6, 8, 0)


def test_hard_constraints_counts_hard_only() -> None:
    tasks = (
        make_task(1, constraint_type=ConstraintType.MSO, constraint_date=DATE),  # hard
        make_task(2, constraint_type=ConstraintType.SNET, constraint_date=DATE),  # soft
        make_task(3),  # ASAP
        make_task(4),  # ASAP
    )
    result = run_hard_constraints(make_schedule(tasks=tasks, relations=()))
    assert result.metric_id == 5
    assert (result.numerator, result.denominator) == (1, 4)
    assert {o.unique_id for o in result.offenders} == {1}  # MSO is hard; SNET is not
    assert result.severity == Severity.FAIL


def test_hard_constraints_none_passes() -> None:
    tasks = tuple(make_task(i) for i in range(1, 4))
    result = run_hard_constraints(make_schedule(tasks=tasks, relations=()))
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_hard_constraints_empty_raises() -> None:
    with pytest.raises(MetricError):
        run_hard_constraints(make_schedule(tasks=(), relations=()))
