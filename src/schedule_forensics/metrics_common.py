"""Shared contract for analysis metrics (DCMA-14, indices, driving-path, SRA, ...).

Every metric returns a :class:`MetricResult`. Each metric's threshold is defined
ONCE, in its own module, as a :class:`Threshold` carrying a cited authoritative
source (single source of truth -- H-DRIFT-2). Capabilities beyond what
Acumen/SSI/MS Project produce are flagged ``is_extension=True`` (parity-honesty
rule). A metric that cannot run on the supplied data returns status SKIPPED with
a reason -- it NEVER fabricates a number (H-DRIFT-1).

Offenders are TYPED (``Offender`` with an explicit ``kind``) rather than an
overloaded float, which was the prior build's clearest design debt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MetricStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"  # un-runnable on the given data; never a fabricated value


class Direction(StrEnum):
    """Comparison that must hold for a metric to PASS."""

    LE = "<="  # measured <= threshold
    GE = ">="  # measured >= threshold
    EQ = "=="  # measured == threshold


@dataclass(frozen=True)
class Threshold:
    """A single metric threshold with its authoritative citation (defined once)."""

    value: float
    direction: Direction
    source: str  # REFERENCES.md key + locator, e.g. "DCMA-EDWARDS p.X / DECM row Y"


@dataclass(frozen=True)
class Offender:
    """One task/relationship contributing to a finding (typed, not an overloaded float)."""

    unique_id: int
    kind: str  # what ``value`` means, e.g. "lag_minutes", "total_float_minutes"
    value: float
    detail: str = ""


@dataclass(frozen=True)
class MetricResult:
    """The outcome of evaluating one metric."""

    metric_id: str
    name: str
    status: MetricStatus
    measured: float | None = None
    threshold: float | None = None
    direction: Direction | None = None
    source: str = ""
    is_extension: bool = False
    offenders: tuple[Offender, ...] = ()
    detail: str = ""


def evaluate(
    metric_id: str,
    name: str,
    measured: float,
    threshold: Threshold,
    *,
    offenders: tuple[Offender, ...] = (),
    detail: str = "",
    is_extension: bool = False,
) -> MetricResult:
    """Apply ``threshold`` to ``measured`` and return a PASS/FAIL MetricResult."""
    if threshold.direction is Direction.LE:
        ok = measured <= threshold.value
    elif threshold.direction is Direction.GE:
        ok = measured >= threshold.value
    else:
        ok = measured == threshold.value
    return MetricResult(
        metric_id=metric_id,
        name=name,
        status=MetricStatus.PASS if ok else MetricStatus.FAIL,
        measured=measured,
        threshold=threshold.value,
        direction=threshold.direction,
        source=threshold.source,
        is_extension=is_extension,
        offenders=offenders,
        detail=detail,
    )


def skipped(metric_id: str, name: str, reason: str) -> MetricResult:
    """A metric that cannot run on the supplied data (missing inputs). Never faked."""
    return MetricResult(metric_id=metric_id, name=name, status=MetricStatus.SKIPPED, detail=reason)
