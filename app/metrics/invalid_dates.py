"""DCMA Metric 9 — Invalid Dates (actual/progress data inconsistent with the data date)."""

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
    value=0.0,
    direction=Direction.AT_MOST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 9 (Invalid Dates): "
        "0% — no actual date after the data date; progress and actual dates consistent"
    ),
)


def _is_invalid(task: Task, status_date: datetime) -> bool:
    # Actual work cannot have happened after the data date.
    if task.actual_start is not None and task.actual_start > status_date:
        return True
    if task.actual_finish is not None and task.actual_finish > status_date:
        return True
    # Progress and actual dates must agree.
    if task.percent_complete == 100 and task.actual_finish is None:
        return True
    if 0 < task.percent_complete < 100 and task.actual_start is None:
        return True
    return task.percent_complete == 0 and task.actual_start is not None


def run_invalid_dates(schedule: Schedule, options: MetricOptions | None = None) -> MetricResult:
    """Tasks whose actual dates fall after the data date, or whose progress and actual dates
    disagree. Offender ``value`` is a flag (1.0).

    NOTE: the complementary "forecast remaining work scheduled before the data date" check is
    deferred — it needs data-date (progress) scheduling in the CPM engine, which is not built.
    """
    if schedule.status_date is None:
        raise MetricError("invalid-dates metric requires the schedule status_date")
    tasks = schedule.tasks
    if not tasks:
        raise MetricError("invalid-dates metric requires at least one task")
    status_date = schedule.status_date

    offenders = [Offender(t.unique_id, t.name, 1.0) for t in tasks if _is_invalid(t, status_date)]
    offenders.sort(key=lambda offender: offender.unique_id)
    numerator = len(offenders)
    denominator = len(tasks)
    severity = evaluate_severity(100.0 * numerator / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=9,
        metric_name="Invalid Dates (actuals vs data date)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=denominator,
        offenders=tuple(offenders),
    )
