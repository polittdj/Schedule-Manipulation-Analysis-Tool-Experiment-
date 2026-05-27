"""Earned-value schedule indices: SPI and SPI(t) (Lipke earned schedule).

These indices exist only behind the deliberate schema **v1.1.0** bump that added
``Task.budgeted_cost`` (the budget-at-completion / EV basis) and
``Task.baseline_start`` (needed, with the existing ``baseline_finish``, to
time-phase the planned-value curve). They are computed over NON-SUMMARY tasks
that carry a positive ``budgeted_cost`` AND both baseline dates; a task missing
any of those is excluded. If no task qualifies -- or there is no ``status_date``
-- the metric returns SKIPPED with a reason: it NEVER fabricates an index from
absent earned-value data (LAW 2 / H-DRIFT-1).

Definitions (working-minute axis from ``project_start``; see ``cpm``):

  * **EV (BCWP)** = sum over tasks of ``budgeted_cost * percent_complete/100``
    -- the earned value as of the status date.
  * **PV (BCWS)(t)** = sum over tasks of ``budgeted_cost * planned_fraction(t)``,
    where ``planned_fraction`` ramps linearly from 0 at ``baseline_start`` to 1
    at ``baseline_finish`` (the standard linear-spend assumption absent a detailed
    spend curve; a zero-length baseline -- a milestone -- jumps 0->1 at its date).
  * **SPI** = EV / PV(status). >= 1 means at/ahead of the planned spend.
  * **SPI(t)** = ES / AT (Lipke earned schedule). ES ("earned schedule") is the
    time at which the baseline PV curve first equals the current EV, found by
    inverting the piecewise-linear, non-decreasing PV(t); AT ("actual time") is
    the working-minute offset of the status date from ``project_start``. SPI(t)
    keeps degrading once the project runs past its baseline finish, where the
    cost-based SPI spuriously recovers toward 1 as PV plateaus at BAC -- the
    reason earned schedule exists.

Threshold: 0.95 (GE) -- a common EVM management "traffic-light" watch level
(green > 0.95), NOT a codified standard trip and NOT a DCMA-14 check (SPI/SPI(t)
are not among the 14). The index itself is standard EVM (ANSI/EIA-748);
authoritative guidance (GAO Cost Estimating & Assessment Guide; NDIA IPMD) favours
*trend* over a fixed point value, so 0.95 is a program-configurable default. It is
labelled accordingly and remains source-pending in docs/REFERENCES.md.

NOTE (no cost-efficiency index here): a cost-efficiency CPI = EV/AC is NOT
implemented -- it would need an ``actual_cost`` field this schema does not carry,
and per LAW 2 we ship no guessed formula. That is distinct from the **Current
Execution Index (CEI)**, a count-based per-period throughput metric (PASEG 10.4.5)
that IS implemented separately in ``cei.py``; CEI is not an earned-value cost index
and so is deliberately not duplicated here (see docs/REFERENCES.md).

Single source of truth (H-DRIFT-2): each threshold is a module-level
:class:`~schedule_forensics.metrics_common.Threshold`; a parametrized test pins
value, direction, and a non-empty cited source. BEI (DCMA-14) is a separate,
count-based index implemented in ``dcma_progress`` and is NOT duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass

from schedule_forensics.cpm import datetime_to_offset
from schedule_forensics.metrics_common import (
    Direction,
    MetricResult,
    Threshold,
    evaluate,
    skipped,
)
from schedule_forensics.schemas import Schedule

_SRC_SPI = (
    "NASA-EVM / ANSI-EIA-748 EVM index SPI = BCWP/BCWS (earned value / planned value). "
    "0.95 is a common management traffic-light watch level (green >0.95), not a codified "
    "trip and not a DCMA-14 check; GAO Cost Estimating & Assessment Guide and NDIA IPMD "
    "favour trend, so 0.95 is a program-configurable default (source-pending)"
)
_SRC_SPIT = (
    "NASA-EVM / Lipke earned schedule SPI(t) = ES/AT (index per ANSI-EIA-748; Lipke, "
    "'Earned Schedule'). 0.95 is the same management traffic-light watch level, not "
    "codified and not a DCMA-14 check; GAO and NDIA IPMD favour trend, so 0.95 is a "
    "program-configurable default (source-pending)"
)

THRESHOLD_SPI = Threshold(value=0.95, direction=Direction.GE, source=_SRC_SPI)
THRESHOLD_SPIT = Threshold(value=0.95, direction=Direction.GE, source=_SRC_SPIT)


@dataclass(frozen=True)
class _EVTask:
    """A task's earned-value components on the working-minute axis."""

    budget: float
    pct: float  # actual percent complete, 0..100
    bs_off: int  # baseline-start offset
    bf_off: int  # baseline-finish offset


def _ev_components(schedule: Schedule) -> list[_EVTask]:
    """Non-summary tasks with budgeted_cost > 0 and both baseline dates present."""
    components: list[_EVTask] = []
    for task in schedule.tasks:
        if task.is_summary or task.budgeted_cost <= 0.0:
            continue
        if task.baseline_start is None or task.baseline_finish is None:
            continue
        components.append(
            _EVTask(
                budget=task.budgeted_cost,
                pct=task.percent_complete,
                bs_off=datetime_to_offset(
                    schedule.project_start, task.baseline_start, schedule.calendar
                ),
                bf_off=datetime_to_offset(
                    schedule.project_start, task.baseline_finish, schedule.calendar
                ),
            )
        )
    return components


def _planned_fraction(component: _EVTask, t_off: int) -> float:
    """Planned (baseline) fraction complete of one task at offset ``t_off`` (0..1)."""
    if component.bf_off <= component.bs_off:  # zero-length baseline (milestone)
        return 1.0 if t_off >= component.bf_off else 0.0
    if t_off <= component.bs_off:
        return 0.0
    if t_off >= component.bf_off:
        return 1.0
    return (t_off - component.bs_off) / (component.bf_off - component.bs_off)


def _planned_value(components: list[_EVTask], t_off: int) -> float:
    return sum(c.budget * _planned_fraction(c, t_off) for c in components)


def _earned_value(components: list[_EVTask]) -> float:
    return sum(c.budget * (c.pct / 100.0) for c in components)


def _earned_schedule(components: list[_EVTask], earned_value: float) -> float:
    """Invert the PV curve: the offset at which baseline PV first equals ``earned_value``.

    PV(t) is piecewise-linear and non-decreasing (a sum of clamped linear ramps),
    so the crossing is found exactly by walking its breakpoints (each task's
    baseline start/finish) and interpolating within the bracketing segment.
    """
    bac = sum(c.budget for c in components)
    if earned_value <= 0.0:
        return 0.0
    if earned_value >= bac:  # fully earned -> ES caps at the latest baseline finish
        return float(max(c.bf_off for c in components))

    breakpoints = sorted({0} | {c.bs_off for c in components} | {c.bf_off for c in components})
    prev_off = breakpoints[0]
    prev_pv = _planned_value(components, prev_off)
    for off in breakpoints[1:]:
        pv = _planned_value(components, off)
        if pv >= earned_value:
            if pv == prev_pv:  # flat segment exactly at the crossing
                return float(prev_off)
            fraction = (earned_value - prev_pv) / (pv - prev_pv)
            return prev_off + fraction * (off - prev_off)
        prev_off, prev_pv = off, pv
    return float(breakpoints[-1])  # unreachable given earned_value < bac, defensive


def compute_spi(schedule: Schedule) -> MetricResult:
    """SPI = EV / PV(status). SKIPPED if no EV data or PV(status) == 0."""
    if schedule.status_date is None:
        return skipped("SPI", "Schedule Performance Index", "schedule has no status_date")
    components = _ev_components(schedule)
    if not components:
        return skipped(
            "SPI",
            "Schedule Performance Index",
            "no non-summary task carries budgeted_cost + baseline_start + baseline_finish",
        )
    status_off = datetime_to_offset(schedule.project_start, schedule.status_date, schedule.calendar)
    planned = _planned_value(components, status_off)
    if planned <= 0.0:
        return skipped(
            "SPI",
            "Schedule Performance Index",
            "planned value (BCWS) at the status date is 0 (nothing baselined in progress yet)",
        )
    earned = _earned_value(components)
    spi = earned / planned
    bac = sum(c.budget for c in components)
    detail = f"SPI = EV {earned:.2f} / PV {planned:.2f} = {spi:.4f} (BAC {bac:.2f})"
    return evaluate("SPI", "Schedule Performance Index", spi, THRESHOLD_SPI, detail=detail)


def compute_spi_t(schedule: Schedule) -> MetricResult:
    """SPI(t) = ES / AT (earned schedule). SKIPPED if no EV data or AT == 0."""
    if schedule.status_date is None:
        return skipped("SPI(t)", "Earned Schedule SPI(t)", "schedule has no status_date")
    components = _ev_components(schedule)
    if not components:
        return skipped(
            "SPI(t)",
            "Earned Schedule SPI(t)",
            "no non-summary task carries budgeted_cost + baseline_start + baseline_finish",
        )
    actual_time = datetime_to_offset(
        schedule.project_start, schedule.status_date, schedule.calendar
    )
    if actual_time <= 0:
        return skipped(
            "SPI(t)",
            "Earned Schedule SPI(t)",
            "actual time (status date - project start) is 0; SPI(t) is undefined",
        )
    earned = _earned_value(components)
    earned_schedule = _earned_schedule(components, earned)
    spi_t = earned_schedule / actual_time
    detail = (
        f"SPI(t) = ES {earned_schedule:.2f} / AT {actual_time} = {spi_t:.4f} "
        f"(EV {earned:.2f} working-minute axis)"
    )
    return evaluate("SPI(t)", "Earned Schedule SPI(t)", spi_t, THRESHOLD_SPIT, detail=detail)


def run_performance_indices(schedule: Schedule) -> tuple[MetricResult, ...]:
    """Run the earned-value indices, returned in order (SPI, SPI(t))."""
    return (compute_spi(schedule), compute_spi_t(schedule))
