"""DCMA Metric 5 — Hard Constraints (date constraints that can override logic)."""

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
        "DCMA 14-Point Schedule Assessment, Metric 5 (Hard Constraints): "
        "<= 5% of tasks with a hard date constraint (MSO/MFO/SNLT/FNLT)"
    ),
)


def run_hard_constraints(schedule: Schedule, options: MetricOptions | None = None) -> MetricResult:
    """Tasks carrying a hard constraint (MSO/MFO/SNLT/FNLT) — those that can prevent the
    schedule from staying logic-driven. Offender ``value`` is a flag (1.0); the offending task
    and its constraint are identified by its UniqueID in the schedule."""
    tasks = schedule.tasks
    if not tasks:
        raise MetricError("hard-constraints metric requires at least one task")

    offenders = [Offender(t.unique_id, t.name, 1.0) for t in tasks if t.constraint_type.is_hard]
    offenders.sort(key=lambda offender: offender.unique_id)
    numerator = len(offenders)
    denominator = len(tasks)
    severity = evaluate_severity(100.0 * numerator / denominator, _THRESHOLD)
    return MetricResult(
        metric_id=5,
        metric_name="Hard Constraints (MSO/MFO/SNLT/FNLT)",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=denominator,
        offenders=tuple(offenders),
    )
