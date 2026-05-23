"""Earned-value index tests (SPI, SPI(t)): hand-computed parity, skips, perturbation.

Non-vacuous discipline (H-VACUOUS-TEST): the perturbation test FAILS if the
actual-progress field is not read; the divergence test proves SPI and SPI(t) are
distinct computations (SPI plateaus while SPI(t) keeps degrading past baseline).
EV data is absent on a normal imported schedule, so the SKIP paths matter:
nothing is ever fabricated from missing budgets/baselines (LAW 2).
"""

from __future__ import annotations

import datetime as dt

import pytest

from schedule_forensics.metrics_common import Direction, MetricStatus, Threshold
from schedule_forensics.performance_indices import (
    THRESHOLD_SPI,
    THRESHOLD_SPIT,
    compute_spi,
    compute_spi_t,
    run_performance_indices,
)
from schedule_forensics.schemas import Schedule, Task

_START = dt.datetime(2025, 1, 6, 8)  # Monday -> working-minute offset 0
_D6 = dt.datetime(2025, 1, 6, 8)  # offset 0
_D7 = dt.datetime(2025, 1, 7, 8)  # offset 480
_D8 = dt.datetime(2025, 1, 8, 8)  # offset 960
_D10 = dt.datetime(2025, 1, 10, 8)  # offset 1920


def _task(
    uid: int,
    pct: float,
    baseline_start: dt.datetime | None,
    baseline_finish: dt.datetime | None,
    budget: float = 100.0,
) -> Task:
    return Task(
        unique_id=uid,
        name=f"T{uid}",
        duration_minutes=480,
        percent_complete=pct,
        baseline_start=baseline_start,
        baseline_finish=baseline_finish,
        budgeted_cost=budget,
    )


def _sched(status: dt.datetime | None, *tasks: Task) -> Schedule:
    return Schedule(name="EV", project_start=_START, status_date=status, tasks=tasks)


# ── Single source of truth for thresholds (H-DRIFT-2) ─────────────────────────


@pytest.mark.parametrize("threshold", [THRESHOLD_SPI, THRESHOLD_SPIT])
def test_thresholds_are_cited_and_canonical(threshold: Threshold) -> None:
    assert threshold.value == 0.95
    assert threshold.direction is Direction.GE
    assert threshold.source.strip() != ""


# ── Hand-computed SPI / SPI(t) ────────────────────────────────────────────────


def test_spi_behind_schedule() -> None:
    # T1 (100%, budget 100, baseline 0..480) + T2 (50%, budget 100, baseline 480..960).
    # status @ offset 960: EV = 100 + 50 = 150; PV = 100 + 100 = 200 -> SPI = 0.75.
    sched = _sched(_D8, _task(1, 100.0, _D6, _D7), _task(2, 50.0, _D7, _D8))
    spi = compute_spi(sched)
    assert spi.status is MetricStatus.FAIL  # 0.75 < 0.95
    assert spi.measured == pytest.approx(0.75)


def test_spi_on_schedule_passes() -> None:
    # Both tasks complete by their baseline finish; status @ 960 -> EV = PV = 200 -> SPI 1.0.
    sched = _sched(_D8, _task(1, 100.0, _D6, _D7), _task(2, 100.0, _D7, _D8))
    spi = compute_spi(sched)
    assert spi.status is MetricStatus.PASS
    assert spi.measured == pytest.approx(1.0)


def test_spi_t_matches_spi_at_baseline_finish() -> None:
    # status exactly at baseline finish: ES = 720, AT = 960 -> SPI(t) = 0.75 (== SPI here).
    sched = _sched(_D8, _task(1, 100.0, _D6, _D7), _task(2, 50.0, _D7, _D8))
    spi_t = compute_spi_t(sched)
    assert spi_t.measured == pytest.approx(0.75)


def test_spi_t_diverges_from_spi_past_baseline_finish() -> None:
    # Same EV/PV as 'behind', but status is far past baseline finish (offset 1920).
    # Cost SPI plateaus at 0.75 (PV caps at BAC); earned-schedule SPI(t) keeps
    # degrading: ES still 720, AT now 1920 -> SPI(t) = 0.375. This is the whole
    # point of earned schedule, and proves the two are distinct computations.
    sched = _sched(_D10, _task(1, 100.0, _D6, _D7), _task(2, 50.0, _D7, _D8))
    spi = compute_spi(sched)
    spi_t = compute_spi_t(sched)
    assert spi.measured == pytest.approx(0.75)
    assert spi_t.measured == pytest.approx(0.375)
    assert spi_t.measured < spi.measured


def test_run_performance_indices_order() -> None:
    sched = _sched(_D8, _task(1, 100.0, _D6, _D7), _task(2, 50.0, _D7, _D8))
    results = run_performance_indices(sched)
    assert [r.metric_id for r in results] == ["SPI", "SPI(t)"]


# ── Perturbation discipline (the actual-progress field is read) ───────────────


def test_spi_responds_to_actual_progress() -> None:
    base = _sched(_D8, _task(1, 100.0, _D6, _D7), _task(2, 50.0, _D7, _D8))
    more = _sched(_D8, _task(1, 100.0, _D6, _D7), _task(2, 100.0, _D7, _D8))
    assert compute_spi(base).measured == pytest.approx(0.75)
    assert compute_spi(more).measured == pytest.approx(1.0)  # changed input -> changed SPI


# ── SKIP paths: never fabricate an index from absent EV data ──────────────────


def test_skip_when_no_status_date() -> None:
    sched = _sched(None, _task(1, 100.0, _D6, _D7))
    assert compute_spi(sched).status is MetricStatus.SKIPPED
    assert compute_spi_t(sched).status is MetricStatus.SKIPPED


def test_skip_when_no_budget() -> None:
    # budget 0 -> excluded; no qualifying task -> SKIPPED (not a fabricated 0).
    sched = _sched(_D8, _task(1, 100.0, _D6, _D7, budget=0.0))
    assert compute_spi(sched).status is MetricStatus.SKIPPED
    assert compute_spi_t(sched).status is MetricStatus.SKIPPED


def test_skip_when_baseline_dates_missing() -> None:
    # budget present but no baseline -> cannot time-phase PV -> SKIPPED.
    sched = _sched(_D8, _task(1, 100.0, None, None, budget=100.0))
    assert compute_spi(sched).status is MetricStatus.SKIPPED
    assert compute_spi_t(sched).status is MetricStatus.SKIPPED


def test_skip_when_planned_value_zero() -> None:
    # status precedes every baseline start -> PV(status) == 0 -> SPI undefined -> SKIPPED.
    sched = _sched(_D7, _task(1, 0.0, _D8, _D10))
    spi = compute_spi(sched)
    assert spi.status is MetricStatus.SKIPPED
    assert "planned value" in spi.detail.lower()


def test_spi_t_caps_when_fully_earned() -> None:
    # All work complete by the status date (EV == BAC): ES caps at the latest
    # baseline finish (960); AT == 960 -> SPI(t) == 1.0 (exercises the EV>=BAC path).
    sched = _sched(_D8, _task(1, 100.0, _D6, _D7), _task(2, 100.0, _D7, _D8))
    assert compute_spi(sched).measured == pytest.approx(1.0)
    assert compute_spi_t(sched).measured == pytest.approx(1.0)


def test_milestone_budget_counts_in_planned_value() -> None:
    # A zero-length baseline (milestone, baseline_start == baseline_finish) jumps
    # its planned fraction 0->1 at its date. Milestone @ offset 480, 100% done,
    # status @ 480 -> PV == EV == budget -> SPI 1.0 (not SKIPPED, not div-by-zero).
    milestone = _task(1, 100.0, _D7, _D7)
    spi = compute_spi(_sched(_D7, milestone))
    assert spi.status is MetricStatus.PASS
    assert spi.measured == pytest.approx(1.0)


def test_summary_tasks_excluded() -> None:
    # A summary task with a budget must not contribute (it is a rollup).
    summary = Task(
        unique_id=9,
        name="rollup",
        duration_minutes=0,
        is_summary=True,
        budgeted_cost=1000.0,
        baseline_start=_D6,
        baseline_finish=_D8,
    )
    sched = _sched(_D8, summary, _task(1, 100.0, _D6, _D7), _task(2, 50.0, _D7, _D8))
    # If the summary leaked in, EV/PV would change; SPI must still be 0.75.
    assert compute_spi(sched).measured == pytest.approx(0.75)
