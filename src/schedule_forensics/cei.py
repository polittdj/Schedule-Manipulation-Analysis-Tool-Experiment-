"""Current Execution Index (CEI) -- per-period schedule-throughput (PASEG 10.4.5).

CEI answers, for each reporting period: *of the tasks the schedule FORECAST (at
the start of the period) to finish in this period, how many ACTUALLY finished in
this period?* It is a count-based, finish-only, per-period ratio -- NOT dollars,
duration, or %-complete, and NOT cumulative.

CEI vs BEI (the critical distinction): BEI's denominator is the BASELINE finish
dates and is cumulative and can exceed 1.0; CEI's denominator is the period-START
FORECAST finish dates (frozen) and is per-period and CANNOT exceed 1.0 (the
numerator is a strict subset of the denominator). BEI lives in ``dcma_progress``.

Sources (LAW 2): PASEG (Planning & Scheduling Excellence Guide) 10.4.5; NDIA IPMD
"A Guide to Managing Programs Using Predictive Measures." See docs/REFERENCES.md.

Inputs: two or more status-dated exports of the SAME schedule. With fewer than
two, CEI is NOT COMPUTABLE -- this raises :class:`CEIError` ("insufficient data")
rather than fabricating a snapshot (spec 5). Versions are ordered by absolute
``status_date`` (reusing ``version_matcher.order_versions``); N versions yield
N-1 periods, one per consecutive pair.

Snapshot reconstruction is a TOOL-ORIGINAL CAPTURE METHOD (spec 5): standard
PASEG/SSI practice has a human snapshot the schedule at each period start; this
tool reconstructs that snapshot from the chronologically-earlier export. The
METRIC is standard; only the CAPTURE is ours -- every period's ``detail`` says so.

Threshold: CEI >= 0.95 is the common dashboard gate, but it is **source-pending /
VERIFY** -- NDIA frames a healthy CEI as trending above the 75th percentile, not
a fixed 0.95; confirm the program's contractual threshold.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from schedule_forensics.metrics_common import Direction, MetricStatus, Threshold
from schedule_forensics.schemas import Schedule, Task
from schedule_forensics.version_matcher import order_versions

_SRC_CEI = (
    "PASEG 10.4.5 / NDIA IPMD Predictive Measures (CEI = finished / forecast-to-finish, "
    "per period); >=0.95 is the common gate but is source-pending (VERIFY the program's "
    "threshold; NDIA prefers a >75th-percentile trend). Snapshot capture is tool-original."
)

# CEI pass gate. Value is the common dashboard threshold; direction GE. Cited above
# but flagged source-pending (the spec's [VERIFY] note).
THRESHOLD_CEI = Threshold(value=0.95, direction=Direction.GE, source=_SRC_CEI)


class CEIError(ValueError):
    """Raised when CEI cannot be computed at all (e.g. fewer than two versions)."""


@dataclass(frozen=True)
class CEIPeriod:
    """CEI for one reporting period ``(period_start, period_end]`` (bounds per spec 6)."""

    period_start: dt.datetime
    period_end: dt.datetime
    denominator: int  # tasks forecast (at period start) to finish in the period
    numerator: int  # of those, the ones that actually finished in the period
    cei: float | None  # numerator / denominator; None == N/A (undefined: empty denominator)
    status: MetricStatus  # PASS/FAIL vs THRESHOLD_CEI; SKIPPED when cei is None
    unmatched_denominator_ids: tuple[int, ...]  # denominator tasks absent from the current file
    detail: str


def _forecast_to_finish_in_period(
    task: Task, period_start: dt.datetime, period_end: dt.datetime
) -> bool:
    """Denominator membership (spec 7): non-summary, incomplete at period start, with a
    frozen forecast finish inside ``(period_start, period_end]``."""
    if task.is_summary:  # exclude Summary lines; Discrete/Milestone/LOE are kept
        return False
    if task.actual_finish is not None:  # incomplete as of the prior file
        return False
    if task.finish is None:  # no forecast finish -> cannot be in the snapshot set
        return False
    return period_start < task.finish <= period_end


def _actually_finished_in_period(
    task: Task, period_start: dt.datetime, period_end: dt.datetime
) -> bool:
    """Numerator membership (spec 7d/7e): actually finished within the period, BOTH ends
    bounded -- a denominator task that finishes in a LATER period does not count here."""
    if task.actual_finish is None:
        return False
    return period_start < task.actual_finish <= period_end


def _compute_period(prior: Schedule, current: Schedule) -> CEIPeriod:
    period_start = prior.status_date
    period_end = current.status_date
    assert period_start is not None and period_end is not None  # order_versions guarantees this

    denominator_tasks = [
        t for t in prior.tasks if _forecast_to_finish_in_period(t, period_start, period_end)
    ]
    denominator = len(denominator_tasks)

    if denominator == 0:
        return CEIPeriod(
            period_start=period_start,
            period_end=period_end,
            denominator=0,
            numerator=0,
            cei=None,
            status=MetricStatus.SKIPPED,
            unmatched_denominator_ids=(),
            detail=(
                f"CEI N/A for ({period_start.date().isoformat()}, "
                f"{period_end.date().isoformat()}]: no tasks were forecast to finish in "
                "this period (empty denominator -- never reported as 0.0 or 1.0)."
            ),
        )

    current_by_id = {t.unique_id: t for t in current.tasks}
    numerator = 0
    unmatched: list[int] = []
    for task in denominator_tasks:
        match = current_by_id.get(task.unique_id)
        if match is None:
            # Unmatched (deleted / ID changed): count as did-not-finish + diagnose
            # (confirmed conservative rule -- drives CEI down, surfaces data quality).
            unmatched.append(task.unique_id)
            continue
        if _actually_finished_in_period(match, period_start, period_end):
            numerator += 1

    cei = numerator / denominator  # <= 1.0 by construction (numerator subset of denominator)
    status = MetricStatus.PASS if cei >= THRESHOLD_CEI.value else MetricStatus.FAIL
    detail = (
        f"CEI = {numerator}/{denominator} = {cei:.2f} for "
        f"({period_start.date().isoformat()}, {period_end.date().isoformat()}]; "
        f"{len(unmatched)} denominator task(s) unmatched in the current file. "
        "Snapshot reconstructed from the prior status-dated file (tool-original capture)."
    )
    return CEIPeriod(
        period_start=period_start,
        period_end=period_end,
        denominator=denominator,
        numerator=numerator,
        cei=cei,
        status=status,
        unmatched_denominator_ids=tuple(unmatched),
        detail=detail,
    )


def compute_cei(schedules: Sequence[Schedule]) -> tuple[CEIPeriod, ...]:
    """Compute CEI for every consecutive period across status-dated schedule versions.

    Requires >= 2 versions (raises :class:`CEIError` otherwise -- spec 5). Versions
    are ordered by absolute ``status_date`` (``order_versions`` raises if any lacks
    one). Returns one :class:`CEIPeriod` per consecutive pair, in chronological order.
    """
    if len(schedules) < 2:
        raise CEIError(
            "insufficient data: CEI requires >= 2 status-dated schedule versions "
            "(one period is formed per consecutive pair). Supply at least two exports."
        )
    ordered = order_versions(schedules)
    return tuple(
        _compute_period(prior, current)
        for prior, current in zip(ordered, ordered[1:], strict=False)
    )
