"""DCMA schedule-quality metrics (1-4). Each metric is a pure function
``run_<name>(schedule, options) -> MetricResult``."""

from __future__ import annotations

from app.metrics.base import MetricOptions, MetricResult, Offender, ThresholdConfig
from app.metrics.duration import run_high_duration
from app.metrics.hard_constraints import run_hard_constraints
from app.metrics.high_float import run_high_float
from app.metrics.invalid_dates import run_invalid_dates
from app.metrics.lags import run_lags
from app.metrics.leads import run_leads
from app.metrics.logic import run_missing_logic
from app.metrics.missed_tasks import run_missed_tasks
from app.metrics.negative_float import run_negative_float
from app.metrics.relationship_types import run_relationship_types
from app.metrics.resources import run_resources

__all__ = [
    "MetricOptions",
    "MetricResult",
    "Offender",
    "ThresholdConfig",
    "run_hard_constraints",
    "run_high_duration",
    "run_high_float",
    "run_invalid_dates",
    "run_lags",
    "run_leads",
    "run_missed_tasks",
    "run_missing_logic",
    "run_negative_float",
    "run_relationship_types",
    "run_resources",
]
