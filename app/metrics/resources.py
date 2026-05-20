"""DCMA Metric 10 — Resources (detail tasks lacking resource assignments)."""

from __future__ import annotations

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
    value=5.0,
    direction=Direction.AT_MOST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 10 (Resources): "
        "<= 5% of detail (non-zero-duration) tasks missing a resource assignment"
    ),
)


def run_resources(schedule: Schedule, options: MetricOptions | None = None) -> MetricResult:
    """Detail tasks (duration > 0) with no resource assigned. Milestones are excluded from the
    denominator. Offender ``value`` is a flag (1.0)."""
    detail = [t for t in schedule.tasks if t.duration_minutes > 0]
    if not detail:
        raise MetricError("resources metric requires at least one detail (non-milestone) task")

    offenders = [Offender(t.unique_id, t.name, 1.0) for t in detail if not t.resource_names]
    offenders.sort(key=lambda offender: offender.unique_id)
    numerator = len(offenders)
    denominator = len(detail)
    severity = evaluate_severity(100.0 * numerator / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=10,
        metric_name="Resources (missing assignment)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=denominator,
        offenders=tuple(offenders),
    )
