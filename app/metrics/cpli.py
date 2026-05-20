"""DCMA Metric 13 — Critical Path Length Index (CPLI)."""

from __future__ import annotations

from datetime import datetime

from app.cpm import CPMResult
from app.cpm.calendar_math import add_working_minutes, working_minutes_between
from app.exceptions import MetricError
from app.metrics.base import MetricOptions, MetricResult, ThresholdConfig, evaluate_severity
from app.models import Calendar, Direction, Schedule

_THRESHOLD = ThresholdConfig(
    value=0.95,
    direction=Direction.AT_LEAST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 13 (CPLI): "
        "(baseline finish - data date) / (forecast finish - data date) >= 0.95"
    ),
)


def _signed_working_minutes(calendar: Calendar, start: datetime, end: datetime) -> int:
    """Working minutes from start to end, negative when end precedes start."""
    if end >= start:
        return working_minutes_between(calendar, start, end)
    return -working_minutes_between(calendar, end, start)


def run_cpli(
    schedule: Schedule, cpm: CPMResult, options: MetricOptions | None = None
) -> MetricResult:
    """CPLI = (baseline finish - data date) / (forecast finish - data date). >= 0.95 is healthy.
    Reported via ``measured`` (an index, not a count percentage)."""
    if schedule.status_date is None:
        raise MetricError("CPLI requires the schedule status_date")
    if schedule.baseline_finish is None:
        raise MetricError("CPLI requires the project baseline_finish")
    calendar = schedule.calendars[0]
    forecast_finish = add_working_minutes(calendar, schedule.project_start, cpm.project_finish)

    remaining = _signed_working_minutes(calendar, schedule.status_date, forecast_finish)
    if remaining <= 0:
        raise MetricError("CPLI requires the forecast finish to be after the data date")
    baseline_gap = _signed_working_minutes(calendar, schedule.status_date, schedule.baseline_finish)
    cpli = baseline_gap / remaining

    severity = evaluate_severity(cpli, _THRESHOLD)
    return MetricResult(
        metric_id=13,
        metric_name="Critical Path Length Index (CPLI)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=0,
        denominator=0,
        offenders=(),
        measured=cpli,
    )
