"""DCMA Metric 11 — Missed Tasks (tasks due by the data date that slipped)."""

from __future__ import annotations

from datetime import datetime

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
    value=5.0,
    direction=Direction.AT_MOST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 11 (Missed Tasks): "
        "<= 5% of tasks due by the data date that finished late or not at all"
    ),
)


def run_missed_tasks(schedule: Schedule, options: MetricOptions | None = None) -> MetricResult:
    """Among tasks whose baseline finish is on/before the data date (i.e. due by now), those
    that have not finished or finished after their baseline. Offender ``value`` is a flag (1.0)."""
    if schedule.status_date is None:
        raise MetricError("missed-tasks metric requires the schedule status_date")
    status_date = schedule.status_date

    due: list[tuple[Task, datetime]] = []
    for task in schedule.tasks:
        baseline = task.baseline_finish
        if baseline is not None and baseline <= status_date:
            due.append((task, baseline))
    if not due:
        raise MetricError(
            "missed-tasks metric requires a task with a baseline finish on/before the data date"
        )

    offenders: list[Offender] = []
    for task, baseline in due:
        missed = task.actual_finish is None or task.actual_finish > baseline
        if missed:
            offenders.append(Offender(task.unique_id, task.name, 1.0))
    offenders.sort(key=lambda offender: offender.unique_id)
    numerator = len(offenders)
    denominator = len(due)
    severity = evaluate_severity(100.0 * numerator / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=11,
        metric_name="Missed Tasks (late vs baseline)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=denominator,
        offenders=tuple(offenders),
    )
