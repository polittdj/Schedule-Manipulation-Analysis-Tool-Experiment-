"""DCMA Metric 7 — High Float (total float greater than 44 working days)."""

from __future__ import annotations

from app.cpm import CPMResult
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

HIGH_FLOAT_WORKING_DAYS = 44.0

_THRESHOLD = ThresholdConfig(
    value=5.0,
    direction=Direction.AT_MOST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 6 (High Float): "
        "<= 5% of tasks with total float > 44 working days"
    ),
)


def run_high_float(
    schedule: Schedule, cpm: CPMResult, options: MetricOptions | None = None
) -> MetricResult:
    """Tasks whose total float exceeds 44 working days. Requires the CPM result for float.
    Offender ``value`` = the total float in working days."""
    tasks = schedule.tasks
    if not tasks:
        raise MetricError("high-float metric requires at least one task")
    calendars = {c.calendar_id: c for c in schedule.calendars}

    offenders: list[Offender] = []
    for task in tasks:
        slack_minutes = cpm.by_id(task.unique_id).total_slack
        slack_days = minutes_to_working_days(slack_minutes, calendars[task.calendar_id])
        if slack_days > HIGH_FLOAT_WORKING_DAYS:
            offenders.append(Offender(task.unique_id, task.name, slack_days))

    offenders.sort(key=lambda offender: offender.unique_id)
    numerator = len(offenders)
    denominator = len(tasks)
    severity = evaluate_severity(100.0 * numerator / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=6,
        metric_name="High Float (> 44 working days)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=denominator,
        offenders=tuple(offenders),
    )
