"""Total-float burn-rate + trend classification across a version series.

TOOL-ORIGINAL EXTENSION (parity-honesty rule, CLAUDE.md / LAW 2)
================================================================
The *inputs* this module consumes are reference-faithful (total float from the
frozen CPM engine; absolute ``status_date`` ordering from the version matcher),
but the **trend taxonomy** (:class:`FloatTrend`) and its **thresholds**
(``SEVERE_EROSION_DAYS``, ``ERODING_DAYS``, ``IMPROVING_DAYS``) are a
*tool-original analytical layer*. Deltek Acumen Fuse, Steelray/SSI and MS Project
report total float per version; classifying a task's float *trajectory* across
versions into named bands is this tool's own construct. It is therefore labeled
an extension here, in :attr:`FloatTrendResult.is_extension`, and must never be
presented to a user as reference-tool parity. The thresholds are not sourced
from DCMA/DECM/Acumen -- they are this tool's defaults, defined ONCE below as the
single source of truth (H-DRIFT-2).

What is objective (and lives elsewhere): the per-version float values and the
version-pair float *deltas* are objective facts, computed by the frozen CPM
engine and reported by :mod:`schedule_forensics.diff_engine` (not flagged as an
extension). This module only adds the trend *interpretation* on top.

Method
------
For each task that appears in >= 1 version (as a *scheduled* activity -- see the
summary note below), its total float is read from each version's CPM result and
converted to WORKING DAYS (``total_float_minutes / 480.0``; 480 working minutes
== one 8-hour day, the project axis). Let:

* ``earliest_float_days`` -- float in the FIRST version (by status_date) the task
  appears in;
* ``latest_float_days``   -- float in the LAST version the task appears in;
* ``net_change_days = latest_float_days - earliest_float_days``.

Classification (first matching band wins; thresholds are the module constants):

* ``CRITICAL``       if ``latest_float_days <= 0``                  (critical now)
* ``SEVERE_EROSION`` else if ``net_change_days <= SEVERE_EROSION_DAYS``
* ``ERODING``        else if ``net_change_days <  ERODING_DAYS``
* ``IMPROVING``      else if ``net_change_days >  IMPROVING_DAYS``
* ``STABLE``         otherwise

``burn_rate_days_per_day = net_change_days / span_days``, where ``span_days`` is
the number of **raw calendar days** between the task's earliest and latest
status dates (``(latest_status - earliest_status).days``). Raw calendar days
(not working days) are used deliberately: burn rate is a wall-clock erosion
velocity -- "float lost per calendar day of project time elapsed" -- which is how
a reviewer reads a status-to-status trend. When ``span_days == 0`` (a single
version, or two versions sharing a status date) the burn rate is ``0.0`` by
definition (no elapsed time over which to measure a rate); the guard prevents a
divide-by-zero and never fabricates a velocity.

Summary tasks: a summary is a date rollup, excluded from the CPM network and
absent from ``CPMResult.timings``. A task counts as "appearing in" a version only
when it is a scheduled activity there; a version in which the task is a summary
contributes no float point. A task that is a summary in *every* version never
appears and yields no :class:`FloatTrendResult`.

Edges & errors: a single-version input yields, per task, ``net_change_days == 0``
and ``n_versions == 1`` -> ``STABLE`` (unless its sole float value is ``<= 0`` ->
``CRITICAL``, which takes precedence by the taxonomy). ``order_versions`` raising
``VersionMatchError`` (missing ``status_date``) or ``compute_cpm`` raising
``CPMError`` (cycle / unsupported constraint) propagate unchanged -- never a
fabricated trend (LAW 2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from schedule_forensics.cpm import compute_cpm
from schedule_forensics.schemas import Schedule
from schedule_forensics.version_matcher import order_versions

# --- single source of truth for the EXTENSION thresholds (H-DRIFT-2) ----------
# Tool-original bands on net total-float change (working days) across the series.
# Not sourced from DCMA/DECM/Acumen -- this tool's defaults. Defined once here.
SEVERE_EROSION_DAYS = -10.0  # net change <= this (very large float loss) -> SEVERE_EROSION
ERODING_DAYS = -1.0  # net change < this (meaningful float loss) -> ERODING
IMPROVING_DAYS = 1.0  # net change > this (meaningful float gain) -> IMPROVING
# The (-1.0, +1.0] net-change interval (and >0 latest float) is STABLE.

# Working minutes per day on the project axis (480 == one 8-hour day). Used only
# to convert CPM total-float minutes into the working-day unit the bands speak.
_MINUTES_PER_DAY = 480.0


class FloatTrend(StrEnum):
    """Tool-original classification of a task's total-float trajectory.

    EXTENSION (not reference-tool parity) -- see the module docstring. The bands
    are evaluated in the order declared in :func:`_classify`; the first match
    wins.
    """

    CRITICAL = "CRITICAL"  # latest total float <= 0 (critical in the latest version)
    SEVERE_EROSION = "SEVERE_EROSION"  # net float change <= SEVERE_EROSION_DAYS
    ERODING = "ERODING"  # net float change < ERODING_DAYS (but > severe band)
    IMPROVING = "IMPROVING"  # net float change > IMPROVING_DAYS
    STABLE = "STABLE"  # net float change within (ERODING_DAYS, IMPROVING_DAYS]


@dataclass(frozen=True)
class FloatTrendResult:
    """The float trend of one task across the version series (EXTENSION output).

    ``is_extension`` is hard-coded ``True``: the *trend* is this tool's analytical
    construct, not a reference-tool metric (parity-honesty rule). All ``*_days``
    fields are WORKING days (``minutes / 480.0``); ``burn_rate_days_per_day`` is
    working-days of float per RAW calendar day of elapsed status time (see the
    module docstring for the calendar-vs-working-day choice). ``n_versions`` is
    how many versions the task appears in as a scheduled activity.
    """

    unique_id: int
    earliest_float_days: float
    latest_float_days: float
    net_change_days: float
    burn_rate_days_per_day: float
    trend: FloatTrend
    n_versions: int
    is_extension: bool = True


def _classify(latest_float_days: float, net_change_days: float) -> FloatTrend:
    """Apply the EXTENSION bands (first match wins). Thresholds are the module
    constants -- the single source of truth (H-DRIFT-2)."""
    if latest_float_days <= 0:
        return FloatTrend.CRITICAL
    if net_change_days <= SEVERE_EROSION_DAYS:
        return FloatTrend.SEVERE_EROSION
    if net_change_days < ERODING_DAYS:
        return FloatTrend.ERODING
    if net_change_days > IMPROVING_DAYS:
        return FloatTrend.IMPROVING
    return FloatTrend.STABLE


def analyze_float_trends(schedules: Sequence[Schedule]) -> tuple[FloatTrendResult, ...]:
    """Classify each task's total-float trajectory across the version series.

    TOOL-ORIGINAL EXTENSION (see the module docstring): every result carries
    ``is_extension=True``. Orders the versions by absolute ``status_date`` via
    :func:`~schedule_forensics.version_matcher.order_versions` (raising
    ``VersionMatchError`` if any version lacks one), computes the CPM for each
    version EXACTLY ONCE, builds each task's status-date-ordered total-float
    series (working days) over the versions in which it is a scheduled activity,
    and returns one :class:`FloatTrendResult` per such task, sorted by
    ``unique_id``. ``CPMError`` propagates unchanged. An empty input yields an
    empty tuple.
    """
    if not schedules:
        return ()
    ordered = order_versions(schedules)  # ascending status_date; raises if any missing
    cpms = [compute_cpm(s) for s in ordered]

    # status_date is guaranteed present for every ordered version (order_versions
    # raises otherwise); pull them once for the span computation.
    statuses = [s.status_date for s in ordered]

    # Per task, the ordered list of (version_index, total_float_minutes) for the
    # versions where it is a scheduled activity (present in that version's CPM).
    series: dict[int, list[tuple[int, int]]] = {}
    for v_idx, cpm in enumerate(cpms):
        for uid, timing in cpm.timings.items():
            series.setdefault(uid, []).append((v_idx, timing.total_float))

    results: list[FloatTrendResult] = []
    for uid in sorted(series):
        points = series[uid]  # already in ascending version order (built in order)
        first_idx, first_tf = points[0]
        last_idx, last_tf = points[-1]

        earliest_days = first_tf / _MINUTES_PER_DAY
        latest_days = last_tf / _MINUTES_PER_DAY
        net_change_days = latest_days - earliest_days

        first_status = statuses[first_idx]
        last_status = statuses[last_idx]
        assert first_status is not None and last_status is not None  # order_versions guards
        span_days = (last_status - first_status).days
        burn_rate = net_change_days / span_days if span_days != 0 else 0.0

        results.append(
            FloatTrendResult(
                unique_id=uid,
                earliest_float_days=earliest_days,
                latest_float_days=latest_days,
                net_change_days=net_change_days,
                burn_rate_days_per_day=burn_rate,
                trend=_classify(latest_days, net_change_days),
                n_versions=len(points),
            )
        )
    return tuple(results)
