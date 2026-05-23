"""Float-trend (EXTENSION) tests against independently hand-computed values.

Every expectation is hand-derived from the CPM arithmetic in each test's comment
(default calendar: 480 working minutes == one 8-hour day, so float_days ==
total_float_minutes / 480.0), NOT read back from the function (LAW 2 /
H-VACUOUS-TEST). ``net_change_days`` and the per-version float-day values are
asserted EXACTLY (they are exact ratios of integers); the burn-rate ratio uses a
float tolerance only because it is an irrational quotient -- its numerator
(net_change_days) and denominator (raw calendar days between status dates) are
both hand-pinned, so the tolerance is IEEE-representation slack, not forensic
"approximately".

The trend taxonomy is a TOOL-ORIGINAL EXTENSION (parity-honesty rule): every
result must carry ``is_extension is True``.

Network: DIAMOND  A(1) -> B(2) -> D(4); A(1) -> C(3) -> D(4).
B is the long (critical) branch; C is the short branch carrying erodable float.
The thresholds under test are the module's single-source-of-truth constants.
"""

from __future__ import annotations

import datetime as dt

import pytest

from schedule_forensics.cpm import CPMError
from schedule_forensics.float_analysis import (
    ERODING_DAYS,
    IMPROVING_DAYS,
    SEVERE_EROSION_DAYS,
    FloatTrend,
    FloatTrendResult,
    analyze_float_trends,
)
from schedule_forensics.schemas import Relation, Schedule, Task
from schedule_forensics.version_matcher import VersionMatchError

_START = dt.datetime(2025, 1, 6, 8)  # Monday 08:00
_S1 = dt.datetime(2025, 1, 6, 8)
_S2 = dt.datetime(2025, 1, 20, 8)  # +14 calendar days
_S3 = dt.datetime(2025, 2, 3, 8)  # +28 calendar days from _S1


def _diamond(b_dur: int, c_dur: int, status: dt.datetime) -> Schedule:
    return Schedule(
        name="v",
        project_start=_START,
        status_date=status,
        tasks=(
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=b_dur),
            Task(unique_id=3, name="C", duration_minutes=c_dur),
            Task(unique_id=4, name="D", duration_minutes=0, is_milestone=True),
        ),
        relations=(
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=4),
            Relation(predecessor_id=3, successor_id=4),
        ),
    )


def _result_for(results: tuple[FloatTrendResult, ...], uid: int) -> FloatTrendResult:
    matches = [r for r in results if r.unique_id == uid]
    assert len(matches) == 1, f"expected one result for {uid}, got {len(matches)}"
    return matches[0]


def test_thresholds_are_the_documented_single_source_values() -> None:
    # H-DRIFT-2: pin the EXTENSION thresholds to their documented values. If any
    # constant is edited away from the spec, this test (and the classifications
    # below) fail -- proving the constants are the single source of truth.
    assert SEVERE_EROSION_DAYS == -10.0
    assert ERODING_DAYS == -1.0
    assert IMPROVING_DAYS == 1.0


def test_eroding_trend_with_positive_latest_float() -> None:
    # B fixed 3d=1440 (long branch). C grows 1d->2d->2.5d across S1,S2,S3.
    #   pf = ef_B = 1920 in every version (C never outlasts B).
    #   tf_C = (pf - dur_C) - es_C, with es_C = 480 (after A=480):
    #     v1 C=480 : ls_C=1920-480=1440 -> tf=1440-480=960 min = 2.0 days
    #     v2 C=960 : ls_C=1920-960=960  -> tf= 960-480=480 min = 1.0 day
    #     v3 C=1200: ls_C=1920-1200=720 -> tf= 720-480=240 min = 0.5 day
    # Series 2.0, 1.0, 0.5: earliest 2.0, latest 0.5, net = -1.5.
    #   latest 0.5 > 0; net -1.5 not <= -10; net -1.5 < -1.0  => ERODING.
    #   span = (S3 - S1).days = 28 calendar days; burn = -1.5 / 28.
    results = analyze_float_trends(
        [
            _diamond(1440, 1200, _S3),  # supplied scrambled on purpose
            _diamond(1440, 480, _S1),
            _diamond(1440, 960, _S2),
        ]
    )
    c = _result_for(results, 3)
    assert c.is_extension is True
    assert c.n_versions == 3
    assert c.earliest_float_days == 2.0
    assert c.latest_float_days == 0.5
    assert c.net_change_days == -1.5
    assert c.trend is FloatTrend.ERODING
    assert c.burn_rate_days_per_day == pytest.approx(-1.5 / 28)

    # B is the critical branch in every version: tf_B == 0 -> latest float <= 0
    # -> CRITICAL (not an erosion band; the latest<=0 rule takes precedence).
    b = _result_for(results, 2)
    assert b.earliest_float_days == 0.0
    assert b.latest_float_days == 0.0
    assert b.net_change_days == 0.0
    assert b.trend is FloatTrend.CRITICAL
    assert b.burn_rate_days_per_day == 0.0  # net 0 over any span

    # Results are sorted by unique_id and cover every scheduled task (A,B,C,D).
    assert tuple(r.unique_id for r in results) == (1, 2, 3, 4)


def test_perturbation_deepens_eroding_to_severe() -> None:
    # H-VACUOUS-TEST: a task whose float drops classifies ERODING, and increasing
    # its LATER-version duration deepens the class to SEVERE_EROSION. Assert both.
    #
    # B fixed 20d=9600 (long branch): ef_B = 480 + 9600 = 10080 = pf. es_C = 480.
    #   tf_C = (10080 - dur_C) - 480.
    #   v1 C=480  : tf = (10080-480)-480   = 9120 min = 19.0 days
    # BEFORE v2 C=1440 (3d): tf = (10080-1440)-480 = 8160 min = 17.0 days
    #   net = 17.0 - 19.0 = -2.0 ; -2.0 not <= -10 ; -2.0 < -1.0 => ERODING.
    before = analyze_float_trends([_diamond(9600, 480, _S1), _diamond(9600, 1440, _S2)])
    c_before = _result_for(before, 3)
    assert c_before.earliest_float_days == 19.0
    assert c_before.latest_float_days == 17.0
    assert c_before.net_change_days == -2.0
    assert c_before.trend is FloatTrend.ERODING

    # AFTER v2 C=5760 (12d): tf = (10080-5760)-480 = 3840 min = 8.0 days
    #   net = 8.0 - 19.0 = -11.0 ; -11.0 <= -10 => SEVERE_EROSION. latest 8.0 > 0.
    after = analyze_float_trends([_diamond(9600, 480, _S1), _diamond(9600, 5760, _S2)])
    c_after = _result_for(after, 3)
    assert c_after.earliest_float_days == 19.0
    assert c_after.latest_float_days == 8.0
    assert c_after.net_change_days == -11.0
    assert c_after.trend is FloatTrend.SEVERE_EROSION

    # The perturbation actually changed the verdict, not merely the inputs.
    assert c_before.trend is not c_after.trend
    assert c_after.net_change_days < c_before.net_change_days


def test_improving_trend_when_float_grows() -> None:
    # B fixed 20d=9600 (pf=10080, es_C=480). C SHRINKS 3d->1d across versions.
    #   v1 C=1440: tf = (10080-1440)-480 = 8160 min = 17.0 days
    #   v2 C=480 : tf = (10080-480)-480  = 9120 min = 19.0 days
    #   net = 19.0 - 17.0 = +2.0 > 1.0 => IMPROVING. latest 19.0 > 0.
    #   span 14 days -> burn = +2.0 / 14.
    results = analyze_float_trends([_diamond(9600, 1440, _S1), _diamond(9600, 480, _S2)])
    c = _result_for(results, 3)
    assert c.earliest_float_days == 17.0
    assert c.latest_float_days == 19.0
    assert c.net_change_days == 2.0
    assert c.trend is FloatTrend.IMPROVING
    assert c.burn_rate_days_per_day == pytest.approx(2.0 / 14)


def test_stable_trend_when_float_unchanged() -> None:
    # B fixed 20d=9600, C fixed 1d=480 across two versions. tf_C = 19.0 both.
    #   net = 0.0, within (ERODING_DAYS, IMPROVING_DAYS]; latest 19.0 > 0 => STABLE.
    results = analyze_float_trends([_diamond(9600, 480, _S1), _diamond(9600, 480, _S2)])
    c = _result_for(results, 3)
    assert c.earliest_float_days == 19.0
    assert c.latest_float_days == 19.0
    assert c.net_change_days == 0.0
    assert c.trend is FloatTrend.STABLE
    assert c.burn_rate_days_per_day == 0.0


def test_critical_takes_precedence_when_latest_float_nonpositive() -> None:
    # C ERODES from 2.0d (v1) to 0.0d (v2): latest float <= 0 => CRITICAL wins,
    # even though net (-2.0) would otherwise be an erosion band. (Same crossing
    # the diff_engine reports as became_critical.)
    #   B=3d=1440 (pf=1920, es_C=480).
    #   v1 C=1d=480 : tf = (1920-480)-480 = 960 min = 2.0 days
    #   v2 C=4d=1920: ef_C = 480+1920 = 2400 -> C becomes the long branch.
    #     New pf = 2400; tf_C = (2400-1920)-480 = 0 min = 0.0 days.
    results = analyze_float_trends([_diamond(1440, 480, _S1), _diamond(1440, 1920, _S2)])
    c = _result_for(results, 3)
    assert c.earliest_float_days == 2.0
    assert c.latest_float_days == 0.0
    assert c.net_change_days == -2.0
    assert c.trend is FloatTrend.CRITICAL


def test_single_version_each_task_stable_or_critical() -> None:
    # Documented 1-version edge: net_change 0, n_versions 1, span 0 -> burn 0.0.
    #   C float 19.0 (>0) -> STABLE; A/B/D float 0 -> CRITICAL.
    (results) = analyze_float_trends([_diamond(9600, 480, _S1)])
    c = _result_for(results, 3)
    assert c.n_versions == 1
    assert c.earliest_float_days == 19.0
    assert c.latest_float_days == 19.0
    assert c.net_change_days == 0.0
    assert c.burn_rate_days_per_day == 0.0
    assert c.trend is FloatTrend.STABLE

    a = _result_for(results, 1)
    assert a.n_versions == 1
    assert a.latest_float_days == 0.0
    assert a.trend is FloatTrend.CRITICAL


def test_every_result_is_flagged_extension() -> None:
    # Parity-honesty rule: the trend taxonomy is tool-original; never claim parity.
    results = analyze_float_trends([_diamond(9600, 480, _S1), _diamond(9600, 1440, _S2)])
    assert results  # non-empty
    assert all(r.is_extension is True for r in results)


def test_task_added_in_later_version_counts_only_versions_it_appears_in() -> None:
    # Task 5 is absent in v1 and present in v2 only; its series has length 1, so
    # net_change == 0, n_versions == 1. Tasks present in both keep n_versions == 2.
    #   v2 adds task 5 as a parallel short branch off A into D.
    v1 = _diamond(9600, 480, _S1)
    v2 = Schedule(
        name="v2",
        project_start=_START,
        status_date=_S2,
        tasks=(
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=9600),
            Task(unique_id=3, name="C", duration_minutes=480),
            Task(unique_id=4, name="D", duration_minutes=0, is_milestone=True),
            Task(unique_id=5, name="E", duration_minutes=480),
        ),
        relations=(
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=4),
            Relation(predecessor_id=3, successor_id=4),
            Relation(predecessor_id=1, successor_id=5),
            Relation(predecessor_id=5, successor_id=4),
        ),
    )
    results = analyze_float_trends([v1, v2])
    five = _result_for(results, 5)
    assert five.n_versions == 1  # only present in v2
    assert five.net_change_days == 0.0
    c = _result_for(results, 3)
    assert c.n_versions == 2  # present in both


def test_summary_only_task_yields_no_result() -> None:
    # A task that is a summary in every version is absent from CPM timings and
    # never "appears"; it produces no FloatTrendResult.
    def build(status: dt.datetime) -> Schedule:
        return Schedule(
            name="v",
            project_start=_START,
            status_date=status,
            tasks=(
                Task(unique_id=99, name="Phase", duration_minutes=0, is_summary=True),
                Task(unique_id=2, name="A", duration_minutes=480),
            ),
            relations=(),
        )

    results = analyze_float_trends([build(_S1), build(_S2)])
    assert all(r.unique_id != 99 for r in results)
    assert any(r.unique_id == 2 for r in results)


def test_empty_input_yields_empty_tuple() -> None:
    assert analyze_float_trends([]) == ()


def test_missing_status_date_propagates() -> None:
    # Fail closed (LAW 2): a version without status_date cannot be ordered.
    good = _diamond(9600, 480, _S1)
    bad = Schedule(
        name="nostatus",
        project_start=_START,
        status_date=None,
        tasks=(Task(unique_id=1, name="A", duration_minutes=480),),
    )
    with pytest.raises(VersionMatchError):
        analyze_float_trends([good, bad])


def test_cycle_propagates_cpm_error() -> None:
    # Never fabricate a trend on an unschedulable network.
    good = _diamond(9600, 480, _S1)
    cyclic = Schedule(
        name="cyclic",
        project_start=_START,
        status_date=_S2,
        tasks=(
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ),
        relations=(
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=1),
        ),
    )
    with pytest.raises(CPMError):
        analyze_float_trends([good, cyclic])
