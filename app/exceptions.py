"""Domain exception hierarchy.

Deliberately free of web-framework imports so the fidelity core (models, CPM engine,
metrics) can raise these without taking a dependency on Flask.
"""

from __future__ import annotations


class ScheduleToolError(Exception):
    """Base class for all domain errors raised by this tool."""


class CPMError(ScheduleToolError):
    """Raised when the CPM engine cannot produce a result (e.g. cyclic logic)."""


class MetricError(ScheduleToolError):
    """Raised when a metric cannot be computed (e.g. an empty denominator)."""
