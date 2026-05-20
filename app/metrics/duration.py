"""DCMA Metric 6 — High Duration (tasks longer than 44 working days)."""

from __future__ import annotations

from app.cpm.calendar_math import minutes_to_working_days
from app.exceptions import MetricError
from app.metrics.base import (
    MetricOptions,
    MetricResult,
    Offender,
    ThresholdConfig,
    evaluate_severity,
)
from app.models import Direction, Schedule

HIGH_DURATION_WORKING_DAYS = 44.0

_THRESHOLD = ThresholdConfig(
    value=5.0,
    direction=Direction.AT_MOST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 8 (High Duration): "
        "<= 5% of tasks with duration > 44 working days"
    ),
)


def run_high_duration(schedule: Schedule, options: MetricOptions | None = None) -> MetricResult:
    """Tasks whose duration exceeds 44 working days (per the task's own calendar).
    Offender ``value`` = the duration in working days."""
    tasks = schedule.tasks
    if not tasks:
        raise MetricError("high-duration metric requires at least one task")
    calendars = {c.calendar_id: c for c in schedule.calendars}

    offenders: list[Offender] = []
    for task in tasks:
        working_days = minutes_to_working_days(task.duration_minutes, calendars[task.calendar_id])
        if working_days > HIGH_DURATION_WORKING_DAYS:
            offenders.append(Offender(task.unique_id, task.name, working_days))

    offenders.sort(key=lambda offender: offender.unique_id)
    numerator = len(offenders)
    denominator = len(tasks)
    severity = evaluate_severity(100.0 * numerator / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=8,
        metric_name="High Duration (> 44 working days)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=denominator,
        offenders=tuple(offenders),
    )
