"""DCMA Metric 14 — Baseline Execution Index (BEI)."""

from __future__ import annotations

from app.exceptions import MetricError
from app.metrics.base import (
    MetricOptions,
    MetricResult,
    Offender,
    ThresholdConfig,
    evaluate_severity,
)
from app.models import Direction, Schedule, Task

_THRESHOLD = ThresholdConfig(
    value=95.0,
    direction=Direction.AT_LEAST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 14 (BEI): "
        "tasks completed / tasks baselined to complete by the data date >= 95%"
    ),
)


def _is_complete(task: Task) -> bool:
    return task.actual_finish is not None or task.percent_complete == 100


def run_bei(schedule: Schedule, options: MetricOptions | None = None) -> MetricResult:
    """BEI = (# tasks completed) / (# tasks baselined to finish by the data date). The numerator
    counts all completed tasks (early completions help); offenders are the due-but-unfinished."""
    if schedule.status_date is None:
        raise MetricError("BEI requires the schedule status_date")
    status_date = schedule.status_date

    due = [
        t
        for t in schedule.tasks
        if t.baseline_finish is not None and t.baseline_finish <= status_date
    ]
    if not due:
        raise MetricError("BEI requires a task baselined to finish on/before the data date")

    completed = sum(1 for t in schedule.tasks if _is_complete(t))
    offenders = [Offender(t.unique_id, t.name, 1.0) for t in due if not _is_complete(t)]
    offenders.sort(key=lambda offender: offender.unique_id)
    denominator = len(due)
    severity = evaluate_severity(100.0 * completed / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=14,
        metric_name="Baseline Execution Index (BEI)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=completed,
        denominator=denominator,
        offenders=tuple(offenders),
    )
