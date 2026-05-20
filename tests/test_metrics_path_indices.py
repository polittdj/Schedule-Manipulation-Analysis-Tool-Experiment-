"""DCMA Metrics 12 (Critical Path Test), 13 (CPLI), 14 (BEI) — known-answer tests.

Project start is Mon 2026-01-05 08:00; 8h/day -> 1 working day = 480 min.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.cpm import compute_cpm
from app.exceptions import MetricError
from app.metrics import run_bei, run_cpli, run_critical_path_test
from app.models import ConstraintType, Severity
from tests.conftest import make_relation, make_schedule, make_task

DAY = 480
STATUS = datetime(2026, 1, 8, 8, 0)  # Thu, 3 working days in


# --- Metric 12: Critical Path Test -----------------------------------------------------


def test_critical_path_test_passes_when_delay_propagates() -> None:
    tasks = tuple(make_task(i, duration_minutes=DAY) for i in range(1, 4))
    schedule = make_schedule(
        tasks=tasks, relations=tuple(make_relation(i, i + 1) for i in range(1, 3))
    )
    result = run_critical_path_test(schedule, compute_cpm(schedule))
    assert result.metric_id == 12
    assert result.numerator == 0
    assert result.severity == Severity.PASS


def test_critical_path_test_fails_when_constraint_absorbs_delay() -> None:
    # A lone Must-Finish-On task: bumping its duration cannot move the pinned finish.
    mfo = datetime(2026, 1, 9, 16, 0)
    tasks = (
        make_task(1, duration_minutes=DAY, constraint_type=ConstraintType.MFO, constraint_date=mfo),
    )
    schedule = make_schedule(tasks=tasks, relations=())
    result = run_critical_path_test(schedule, compute_cpm(schedule))
    assert result.numerator == 1
    assert result.severity == Severity.FAIL
    assert result.offenders[0].unique_id == 1


# --- Metric 13: CPLI -------------------------------------------------------------------


def _two_day_chain() -> tuple[object, ...]:
    return tuple(make_task(i, duration_minutes=DAY) for i in range(1, 3))


def test_cpli_on_track_passes() -> None:
    # data date = project start; forecast finish = 2 working days out; baseline == forecast.
    schedule = make_schedule(
        tasks=_two_day_chain(),
        relations=(make_relation(1, 2),),
        status_date=datetime(2026, 1, 5, 8, 0),
        baseline_finish=datetime(2026, 1, 6, 16, 0),
    )
    result = run_cpli(schedule, compute_cpm(schedule))
    assert result.metric_id == 13
    assert result.measured == 1.0
    assert result.severity == Severity.PASS


def test_cpli_behind_fails() -> None:
    # baseline only 1 working day out vs a 2-working-day forecast -> CPLI 0.5.
    schedule = make_schedule(
        tasks=_two_day_chain(),
        relations=(make_relation(1, 2),),
        status_date=datetime(2026, 1, 5, 8, 0),
        baseline_finish=datetime(2026, 1, 5, 16, 0),
    )
    result = run_cpli(schedule, compute_cpm(schedule))
    assert result.measured == 0.5
    assert result.severity == Severity.FAIL


def test_cpli_requires_status_and_baseline() -> None:
    schedule = make_schedule(tasks=_two_day_chain(), relations=(make_relation(1, 2),))
    with pytest.raises(MetricError):
        run_cpli(schedule, compute_cpm(schedule))


# --- Metric 14: BEI --------------------------------------------------------------------


def test_bei_on_track_passes() -> None:
    due = datetime(2026, 1, 6, 16, 0)  # before the data date
    tasks = (
        make_task(
            1,
            baseline_finish=due,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 6, 16, 0),
        ),
    )
    result = run_bei(make_schedule(tasks=tasks, relations=(), status_date=STATUS))
    assert result.metric_id == 14
    assert (result.numerator, result.denominator) == (1, 1)
    assert result.severity == Severity.PASS


def test_bei_behind_fails() -> None:
    due = datetime(2026, 1, 6, 16, 0)
    tasks = (
        make_task(
            1,
            baseline_finish=due,
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 6, 16, 0),
        ),
        make_task(2, baseline_finish=due),  # due, not done
        make_task(3, baseline_finish=due),  # due, not done
    )
    result = run_bei(make_schedule(tasks=tasks, relations=(), status_date=STATUS))
    assert (result.numerator, result.denominator) == (1, 3)
    assert result.severity == Severity.FAIL
    assert {o.unique_id for o in result.offenders} == {2, 3}


def test_bei_requires_status_and_due() -> None:
    with pytest.raises(MetricError):
        run_bei(make_schedule(tasks=(make_task(1),), relations=()))
