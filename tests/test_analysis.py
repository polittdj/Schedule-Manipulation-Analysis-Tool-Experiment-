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
