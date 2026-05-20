"""Analysis orchestration: compose the CPM engine and the DCMA metrics into one report.

This ties the milestones together (M2 model -> M4 CPM -> M5 metrics). It is framework-free;
the Flask route in ``app.routes`` is a thin wrapper over ``analyze_schedule``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.cpm import TaskTiming, compute_cpm
from app.cpm.calendar_math import minutes_to_working_days
from app.exceptions import MetricError
from app.metrics import (
    run_hard_constraints,
    run_high_duration,
    run_high_float,
    run_lags,
    run_leads,
    run_missing_logic,
    run_negative_float,
    run_relationship_types,
)
from app.metrics.base import MetricResult
from app.models import Schedule


@dataclass(frozen=True, slots=True)
class SkippedMetric:
    """A metric that could not run on this schedule (e.g. empty denominator). Recorded
    honestly rather than fabricating a PASS."""

    metric_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    project_start: datetime
    project_finish_minutes: int
    project_finish_working_days: float
    critical_path: tuple[int, ...]
    timings: tuple[TaskTiming, ...]
    minutes_per_working_day: int
    metrics: tuple[MetricResult, ...]
    skipped_metrics: tuple[SkippedMetric, ...]

    def to_dict(self) -> dict[str, Any]:
        critical = set(self.critical_path)
        return {
            "project_start": self.project_start.isoformat(),
            "project_finish_minutes": self.project_finish_minutes,
            "project_finish_working_days": self.project_finish_working_days,
            "critical_path": list(self.critical_path),
            "tasks": [
                {
                    "unique_id": t.unique_id,
                    "early_start_minutes": t.early_start,
                    "early_finish_minutes": t.early_finish,
                    "late_start_minutes": t.late_start,
                    "late_finish_minutes": t.late_finish,
                    "total_slack_minutes": t.total_slack,
                    "free_slack_minutes": t.free_slack,
                    "total_slack_working_days": t.total_slack / self.minutes_per_working_day,
                    "is_critical": t.unique_id in critical,
                }
                for t in self.timings
            ],
            "metrics": [
                {
                    "metric_id": metric.metric_id,
                    "metric_name": metric.metric_name,
                    "severity": metric.severity.value,
                    "threshold": {
                        "value": metric.threshold.value,
                        "direction": metric.threshold.direction.value,
                        "source": metric.threshold.source,
                    },
                    "numerator": metric.numerator,
                    "denominator": metric.denominator,
                    "percentage": metric.percentage,
                    "offenders": [
                        {"unique_id": o.unique_id, "name": o.name, "value": o.value}
                        for o in metric.offenders
                    ],
                }
                for metric in self.metrics
            ],
            "skipped_metrics": [
                {"metric_id": s.metric_id, "reason": s.reason} for s in self.skipped_metrics
            ],
        }


def analyze_schedule(schedule: Schedule) -> AnalysisReport:
    """Run CPM and DCMA Metrics 1-4 over a schedule and assemble a report.

    Raises ``CPMError`` if the critical-path pass cannot run (cyclic logic / no tasks). A
    metric that cannot run (e.g. no relations) is recorded under ``skipped_metrics`` with its
    reason — never fabricated into a PASS. Working-day conversion uses the schedule's first
    calendar (the CPM engine assumes a single shared calendar).
    """
    cpm = compute_cpm(schedule)

    metrics: list[MetricResult] = []
    skipped: list[SkippedMetric] = []

    def run(metric_id: int, runner: Callable[[], MetricResult]) -> None:
        try:
            metrics.append(runner())
        except MetricError as exc:
            skipped.append(SkippedMetric(metric_id=metric_id, reason=str(exc)))

    run(1, lambda: run_missing_logic(schedule))
    run(2, lambda: run_leads(schedule))
    run(3, lambda: run_lags(schedule))
    run(4, lambda: run_relationship_types(schedule))
    run(5, lambda: run_hard_constraints(schedule))
    run(6, lambda: run_high_duration(schedule))
    run(7, lambda: run_high_float(schedule, cpm))
    run(8, lambda: run_negative_float(schedule, cpm))

    presentation_calendar = schedule.calendars[0]
    return AnalysisReport(
        project_start=cpm.project_start,
        project_finish_minutes=cpm.project_finish,
        project_finish_working_days=minutes_to_working_days(
            cpm.project_finish, presentation_calendar
        ),
        critical_path=cpm.critical_path,
        timings=cpm.timings,
        minutes_per_working_day=presentation_calendar.hours_per_day * 60,
        metrics=tuple(metrics),
        skipped_metrics=tuple(skipped),
    )
