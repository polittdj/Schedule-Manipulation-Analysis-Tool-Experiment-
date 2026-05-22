"""Tests for the analysis composition layer + the health-score regression guard."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from schedule_forensics.analysis import analyze_schedule
from schedule_forensics.metrics_common import MetricStatus
from schedule_forensics.schemas import Relation, RelationType, Schedule, Task

_START = dt.datetime(2025, 1, 6, 8)


def _task(uid: int, dur: int = 480, **kwargs: object) -> Task:
    return Task(unique_id=uid, name=f"T{uid}", duration_minutes=dur, **kwargs)  # type: ignore[arg-type]


def _sched(tasks: Iterable[Task], relations: Iterable[Relation] = ()) -> Schedule:
    return Schedule(
        name="t",
        project_start=_START,
        status_date=_START,
        tasks=tuple(tasks),
        relations=tuple(relations),
    )


def test_composes_cpm_dcma_and_driving_path() -> None:
    schedule = _sched(
        [_task(1, 960), _task(2, 480)],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    analysis = analyze_schedule(schedule)
    assert analysis.cpm_error is None
    assert analysis.project_finish == 1440  # 960 + 480, FS chain
    assert len(analysis.dcma) == 14  # all DCMA-01..14 present
    assert analysis.driving_chain == (1, 2)
    assert 1 in analysis.timings and 2 in analysis.timings


def test_health_score_is_derived_not_hardcoded() -> None:
    # The score must equal 100 * passed / runnable computed independently from the
    # DCMA tuple -- proving it is not a hardcoded constant (the "always-100" guard).
    analysis = analyze_schedule(_sched([_task(1, 960), _task(2, 480)]))
    runnable = [m for m in analysis.dcma if m.status in (MetricStatus.PASS, MetricStatus.FAIL)]
    passed = [m for m in runnable if m.status is MetricStatus.PASS]
    assert runnable, "expected at least one runnable DCMA metric"
    assert analysis.health_score == 100.0 * len(passed) / len(runnable)


def test_health_below_100_when_a_metric_fails() -> None:
    # A negative-lag lead guarantees DCMA-02 (Leads) FAILS, so health must be < 100
    # and the finding must be reported (regression guard: a real failure shows).
    schedule = _sched(
        [_task(1, 480), _task(2, 480)],
        [Relation(predecessor_id=1, successor_id=2, type=RelationType.FS, lag_minutes=-240)],
    )
    analysis = analyze_schedule(schedule)
    assert analysis.health_score is not None
    assert analysis.health_score < 100.0
    assert any("Lead" in f for f in analysis.findings)


def test_cyclic_schedule_degrades_safely() -> None:
    # A logic cycle: CPM unavailable -> no finish/driving chain, error surfaced,
    # but structure-only DCMA still run (so health is still computed).
    schedule = _sched(
        [_task(1, 480), _task(2, 480)],
        [Relation(predecessor_id=1, successor_id=2), Relation(predecessor_id=2, successor_id=1)],
    )
    analysis = analyze_schedule(schedule)
    assert analysis.project_finish is None
    assert analysis.driving_chain == ()
    assert analysis.cpm_error is not None and "cycle" in analysis.cpm_error
    assert len(analysis.dcma) == 14
    # CPM-dependent checks skipped; structure-only ones still produce verdicts.
    assert any(m.status is MetricStatus.SKIPPED for m in analysis.dcma)
    assert any(m.status in (MetricStatus.PASS, MetricStatus.FAIL) for m in analysis.dcma)


def test_health_none_when_nothing_runnable() -> None:
    # An empty schedule: every DCMA check SKIPs (no tasks / no relations) -> health None.
    analysis = analyze_schedule(_sched([]))
    assert all(m.status is MetricStatus.SKIPPED for m in analysis.dcma)
    assert analysis.health_score is None
    assert analysis.findings == ()


def test_performance_indices_skipped_without_ev_data() -> None:
    # A normal schedule (no budgeted_cost/baselines) -> SPI/SPI(t) present but SKIPPED,
    # never fabricated.
    analysis = analyze_schedule(_sched([_task(1, 960), _task(2, 480)]))
    assert [m.metric_id for m in analysis.performance_indices] == ["SPI", "SPI(t)"]
    assert all(m.status is MetricStatus.SKIPPED for m in analysis.performance_indices)


def test_performance_indices_computed_with_ev_data_without_moving_health() -> None:
    # Behind-schedule EV inputs -> SPI runnable (FAIL at 0.75); the DCMA-only health
    # score must NOT include the EV index (it stays a function of the DCMA tuple).
    d7, d8 = dt.datetime(2025, 1, 7, 8), dt.datetime(2025, 1, 8, 8)
    schedule = _sched(
        [
            _task(
                1,
                480,
                percent_complete=100.0,
                baseline_start=_START,
                baseline_finish=d7,
                budgeted_cost=100.0,
            ),
            _task(
                2,
                480,
                percent_complete=50.0,
                baseline_start=d7,
                baseline_finish=d8,
                budgeted_cost=100.0,
            ),
        ]
    )
    schedule = schedule.model_copy(update={"status_date": d8})
    analysis = analyze_schedule(schedule)

    spi = next(m for m in analysis.performance_indices if m.metric_id == "SPI")
    assert spi.status is MetricStatus.FAIL
    assert spi.measured is not None and abs(spi.measured - 0.75) < 1e-9

    # Health score is computed purely from the DCMA tuple (EV excluded).
    runnable = [m for m in analysis.dcma if m.status in (MetricStatus.PASS, MetricStatus.FAIL)]
    passed = [m for m in runnable if m.status is MetricStatus.PASS]
    expected = 100.0 * len(passed) / len(runnable) if runnable else None
    assert analysis.health_score == expected
