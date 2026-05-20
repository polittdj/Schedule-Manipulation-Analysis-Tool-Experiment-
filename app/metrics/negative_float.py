"""DCMA Metric 8 — Negative Float (tasks whose total float is below zero)."""

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

_THRESHOLD = ThresholdConfig(
    value=0.0,
    direction=Direction.AT_MOST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 8 (Negative Float): "
        "0% — no task may carry negative total float"
    ),
)


def run_negative_float(
    schedule: Schedule, cpm: CPMResult, options: MetricOptions | None = None
) -> MetricResult:
    """Tasks whose CPM total float is negative (e.g. driven by a missed deadline). Any such task
    is a finding. Offender ``value`` = total float in working days (negative)."""
    tasks = schedule.tasks
    if not tasks:
        raise MetricError("negative-float metric requires at least one task")
    calendars = {c.calendar_id: c for c in schedule.calendars}

    offenders: list[Offender] = []
    for task in tasks:
        slack_minutes = cpm.by_id(task.unique_id).total_slack
        if slack_minutes < 0:
            slack_days = minutes_to_working_days(slack_minutes, calendars[task.calendar_id])
            offenders.append(Offender(task.unique_id, task.name, slack_days))

    offenders.sort(key=lambda offender: offender.unique_id)
    numerator = len(offenders)
    denominator = len(tasks)
    severity = evaluate_severity(100.0 * numerator / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=8,
        metric_name="Negative Float (< 0)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=denominator,
        offenders=tuple(offenders),
    )
