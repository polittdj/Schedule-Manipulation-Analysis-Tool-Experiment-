"""DCMA Metric 12 — Critical Path Test (does a delay on the critical path move the finish?)."""

from __future__ import annotations

from app.cpm import CPMResult, compute_cpm
from app.exceptions import MetricError
from app.metrics.base import (
    MetricOptions,
    MetricResult,
    Offender,
    ThresholdConfig,
    evaluate_severity,
)
from app.models import Direction, Schedule

# DCMA injects a ~600-working-day delay on a critical task and checks the finish moves with it.
_PROBE_WORKING_DAYS = 600

_THRESHOLD = ThresholdConfig(
    value=0.0,
    direction=Direction.AT_MOST,
    source=(
        "DCMA 14-Point Schedule Assessment, Metric 12 (Critical Path Test): a large delay on a "
        "critical task must push the project finish by the same amount (broken logic fails)"
    ),
)


def run_critical_path_test(
    schedule: Schedule, cpm: CPMResult, options: MetricOptions | None = None
) -> MetricResult:
    """Inject a large delay on a critical task, recompute, and confirm the project finish moves
    by the full amount. If it does not, a constraint or broken link is absorbing the delay.
    Offender ``value`` = how far short the finish moved (negative)."""
    if not cpm.critical_path:
        raise MetricError("critical-path test requires a critical path")
    by_id = {t.unique_id: t for t in schedule.tasks}
    target = by_id[cpm.critical_path[0]]
    calendars = {c.calendar_id: c for c in schedule.calendars}
    delay = _PROBE_WORKING_DAYS * calendars[target.calendar_id].hours_per_day * 60

    bumped = target.model_copy(update={"duration_minutes": target.duration_minutes + delay})
    probe_tasks = tuple(bumped if t.unique_id == target.unique_id else t for t in schedule.tasks)
    probe = schedule.model_copy(update={"tasks": probe_tasks})
    moved = compute_cpm(probe).project_finish - cpm.project_finish

    passed = moved == delay
    offenders = () if passed else (Offender(target.unique_id, target.name, float(moved - delay)),)
    numerator = 0 if passed else 1
    severity = evaluate_severity(100.0 * numerator, _THRESHOLD)  # denominator is 1
    return MetricResult(
        metric_id=12,
        metric_name="Critical Path Test",
        severity=severity,
        threshold=_THRESHOLD,
        numerator=numerator,
        denominator=1,
        offenders=offenders,
    )
