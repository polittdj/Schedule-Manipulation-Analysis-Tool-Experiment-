"""Current Execution Index (CEI) tests -- PASEG 10.4.5, per the supplied spec.

Synthetic multi-version schedules (each a different status date) with hand-computed
expectations (H-VACUOUS-TEST). Covers: the worked micro-example, the 1.0 cap
(numerator is a strict subset of the denominator), period boundaries
(lower-exclusive / upper-inclusive), later-period finishes excluded, summaries +
already-complete tasks excluded, the confirmed unmatched-task rule (did-not-finish
+ diagnostic), empty-denominator N/A, and the >=2-files precondition.
"""

from __future__ import annotations

import datetime as dt

import pytest

from schedule_forensics.cei import THRESHOLD_CEI, CEIError, compute_cei
from schedule_forensics.importers.msp_xml import parse_msp_xml_string
from schedule_forensics.metrics_common import Direction, MetricStatus
from schedule_forensics.schemas import Schedule, Task
from schedule_forensics.version_matcher import VersionMatchError

_START = dt.datetime(2025, 1, 1, 8)
_P0 = dt.datetime(2025, 1, 31, 17)  # prior status date
_P1 = dt.datetime(2025, 2, 28, 17)  # current status date
_IN = dt.datetime(2025, 2, 15, 17)  # inside the period (P0, P1]
_LATER = dt.datetime(2025, 3, 15, 17)  # after P1


def _task(
    uid: int,
    *,
    finish: dt.datetime | None = None,
    actual_finish: dt.datetime | None = None,
    is_summary: bool = False,
) -> Task:
    return Task(
        unique_id=uid,
        name=f"T{uid}",
        duration_minutes=480,
        is_summary=is_summary,
        finish=finish,
        actual_finish=actual_finish,
    )


def _version(status: dt.datetime | None, tasks: list[Task]) -> Schedule:
    return Schedule(name="V", project_start=_START, status_date=status, tasks=tuple(tasks))


# ── threshold (single source, cited, VERIFY-flagged) ──────────────────────────


def test_threshold_is_cited_and_verify_flagged() -> None:
    assert THRESHOLD_CEI.value == 0.95
    assert THRESHOLD_CEI.direction is Direction.GE
    assert "PASEG" in THRESHOLD_CEI.source
    assert "source-pending" in THRESHOLD_CEI.source.lower()


# ── core ratio ────────────────────────────────────────────────────────────────


def test_partial_cei_fails() -> None:
    prior = _version(_P0, [_task(i, finish=_IN) for i in (1, 2, 3)])
    current = _version(
        _P1,
        [
            _task(1, finish=_IN, actual_finish=_IN),
            _task(2, finish=_IN, actual_finish=_IN),
            _task(3, finish=_IN),
        ],
    )
    (period,) = compute_cei([prior, current])
    assert (period.denominator, period.numerator) == (3, 2)
    assert period.cei == pytest.approx(2 / 3)
    assert period.status is MetricStatus.FAIL  # < 0.95


def test_perfect_cei_passes() -> None:
    prior = _version(_P0, [_task(i, finish=_IN) for i in (1, 2, 3)])
    current = _version(_P1, [_task(i, finish=_IN, actual_finish=_IN) for i in (1, 2, 3)])
    (period,) = compute_cei([prior, current])
    assert period.cei == pytest.approx(1.0)
    assert period.status is MetricStatus.PASS


def test_cei_capped_at_one_not_inflated_by_out_of_snapshot_finishes() -> None:
    # Task 2 is forecast for a LATER period (not in the snapshot/denominator) but
    # actually finishes early, inside this period. It must NOT count -- the numerator
    # is a strict subset of the denominator, so CEI cannot exceed 1.0.
    prior = _version(_P0, [_task(1, finish=_IN), _task(2, finish=_LATER)])
    current = _version(
        _P1,
        [_task(1, finish=_IN, actual_finish=_IN), _task(2, finish=_LATER, actual_finish=_IN)],
    )
    (period,) = compute_cei([prior, current])
    assert period.denominator == 1  # only task 1 was forecast for this period
    assert period.numerator == 1
    assert period.cei == pytest.approx(1.0)  # not 2.0


# ── period boundaries (spec 6: lower-exclusive, upper-inclusive) ──────────────


def test_period_boundaries_lower_exclusive_upper_inclusive() -> None:
    # A: finish == P1 (upper, inclusive) -> in denom; actual == P1 -> counts.
    # B: finish == P0 (lower, exclusive) -> NOT in denom.
    # C: finish in period -> in denom; actual == P0 (lower, exclusive) -> not counted.
    prior = _version(_P0, [_task(1, finish=_P1), _task(2, finish=_P0), _task(3, finish=_IN)])
    current = _version(
        _P1,
        [
            _task(1, finish=_P1, actual_finish=_P1),
            _task(2, finish=_P0),
            _task(3, finish=_IN, actual_finish=_P0),
        ],
    )
    (period,) = compute_cei([prior, current])
    assert period.denominator == 2  # task 2 (finish == P0) excluded
    assert period.numerator == 1  # task 1 counts (actual == P1); task 3 actual == P0 excluded


def test_later_actual_finish_not_counted() -> None:
    prior = _version(_P0, [_task(1, finish=_IN)])
    current = _version(_P1, [_task(1, finish=_IN, actual_finish=_LATER)])
    (period,) = compute_cei([prior, current])
    assert (period.denominator, period.numerator) == (1, 0)
    assert period.cei == pytest.approx(0.0)


# ── exclusions ────────────────────────────────────────────────────────────────


def test_summary_and_already_complete_excluded_from_denominator() -> None:
    prior = _version(
        _P0,
        [
            _task(1, finish=_IN),  # discrete, incomplete -> in denominator
            _task(
                2, finish=_IN, actual_finish=dt.datetime(2025, 1, 15)
            ),  # complete in prior -> out
            _task(99, finish=_IN, is_summary=True),  # summary -> out
        ],
    )
    current = _version(_P1, [_task(1, finish=_IN, actual_finish=_IN)])
    (period,) = compute_cei([prior, current])
    assert period.denominator == 1
    assert period.cei == pytest.approx(1.0)


# ── unmatched-task rule (confirmed: did-not-finish + diagnostic) ──────────────


def test_unmatched_denominator_task_counts_as_did_not_finish() -> None:
    prior = _version(_P0, [_task(1, finish=_IN), _task(2, finish=_IN)])
    # Task 2 is gone from the current file (deleted or ID changed).
    current = _version(_P1, [_task(1, finish=_IN, actual_finish=_IN)])
    (period,) = compute_cei([prior, current])
    assert period.denominator == 2  # task 2 stays in the denominator
    assert period.numerator == 1  # task 2 is NOT counted as finished
    assert period.unmatched_denominator_ids == (2,)
    assert period.cei == pytest.approx(0.5)


# ── undefined / preconditions ─────────────────────────────────────────────────


def test_empty_denominator_is_na_not_zero_or_one() -> None:
    prior = _version(_P0, [_task(1, finish=_LATER)])  # nothing forecast in (P0, P1]
    current = _version(_P1, [_task(1, finish=_LATER)])
    (period,) = compute_cei([prior, current])
    assert period.denominator == 0
    assert period.cei is None  # N/A -- never 0.0 or 1.0
    assert period.status is MetricStatus.SKIPPED
    assert "N/A" in period.detail


def test_fewer_than_two_versions_raises() -> None:
    with pytest.raises(CEIError, match="insufficient data"):
        compute_cei([_version(_P0, [_task(1, finish=_IN)])])


def test_missing_status_date_propagates() -> None:
    with pytest.raises(VersionMatchError):
        compute_cei([_version(_P0, [_task(1)]), _version(None, [_task(1)])])


# ── multi-version ordering + capture-method note ──────────────────────────────


def test_three_versions_yield_two_ordered_periods() -> None:
    p2 = dt.datetime(2025, 3, 31, 17)
    v0 = _version(_P0, [_task(1, finish=_IN)])
    v1 = _version(_P1, [_task(1, finish=_IN, actual_finish=_IN)])
    v2 = _version(p2, [_task(1, finish=_IN, actual_finish=_IN)])
    periods = compute_cei([v2, v0, v1])  # deliberately unordered -> sorted by status_date
    assert len(periods) == 2
    assert (periods[0].period_start, periods[0].period_end) == (_P0, _P1)
    assert (periods[1].period_start, periods[1].period_end) == (_P1, p2)


def test_detail_documents_tool_original_capture() -> None:
    prior = _version(_P0, [_task(1, finish=_IN)])
    current = _version(_P1, [_task(1, finish=_IN, actual_finish=_IN)])
    (period,) = compute_cei([prior, current])
    assert "tool-original capture" in period.detail.lower()


def test_cei_end_to_end_from_mspdi_imports() -> None:
    # Prove the chain: MSPDI import populates finish + actual_finish + status_date,
    # and CEI computes over the imported versions. Task forecast to finish 2/15,
    # incomplete at 1/31, actually finished 2/15 -> CEI 1/1 = 1.0.
    def _ver(status: str, actual: str | None) -> str:
        actual_el = f"<ActualFinish>{actual}</ActualFinish>" if actual else ""
        return (
            '<Project xmlns="http://schemas.microsoft.com/project">'
            f"<Name>v</Name><StartDate>2025-01-01T08:00:00</StartDate>"
            f"<StatusDate>{status}</StatusDate><Tasks>"
            "<Task><UID>1</UID><Name>A</Name><Duration>PT8H0M0S</Duration>"
            f"<Finish>2025-02-15T17:00:00</Finish>{actual_el}</Task>"
            "</Tasks></Project>"
        )

    prior = parse_msp_xml_string(_ver("2025-01-31T17:00:00", None))
    current = parse_msp_xml_string(_ver("2025-02-28T17:00:00", "2025-02-15T17:00:00"))
    (period,) = compute_cei([prior, current])
    assert (period.denominator, period.numerator) == (1, 1)
    assert period.cei == pytest.approx(1.0)


def test_actual_finish_perturbation_changes_numerator() -> None:
    # Moving an actual finish from inside the period to a later period drops it from
    # the numerator -- proving the field is actually read (H-VACUOUS-TEST).
    prior = _version(_P0, [_task(1, finish=_IN), _task(2, finish=_IN)])
    in_period = _version(
        _P1,
        [_task(1, finish=_IN, actual_finish=_IN), _task(2, finish=_IN, actual_finish=_IN)],
    )
    slipped = _version(
        _P1,
        [_task(1, finish=_IN, actual_finish=_IN), _task(2, finish=_IN, actual_finish=_LATER)],
    )
    assert compute_cei([prior, in_period])[0].numerator == 2
    assert compute_cei([prior, slipped])[0].numerator == 1
