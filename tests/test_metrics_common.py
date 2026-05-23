"""Tests for the shared metric contract (evaluate / skipped / Threshold / Offender)."""

from __future__ import annotations

from schedule_forensics.metrics_common import (
    Direction,
    MetricStatus,
    Offender,
    Threshold,
    evaluate,
    skipped,
)

_SRC = "DCMA-EDWARDS p.X"


def test_le_threshold_pass_and_fail() -> None:
    thr = Threshold(value=5.0, direction=Direction.LE, source=_SRC)
    assert evaluate("M1", "Logic", 5.0, thr).status is MetricStatus.PASS
    assert evaluate("M1", "Logic", 5.01, thr).status is MetricStatus.FAIL


def test_ge_threshold_pass_and_fail() -> None:
    thr = Threshold(value=0.95, direction=Direction.GE, source=_SRC)
    assert evaluate("BEI", "BEI", 0.95, thr).status is MetricStatus.PASS
    assert evaluate("BEI", "BEI", 0.94, thr).status is MetricStatus.FAIL


def test_eq_threshold() -> None:
    thr = Threshold(value=0.0, direction=Direction.EQ, source=_SRC)
    assert evaluate("M8", "Negative Float", 0.0, thr).status is MetricStatus.PASS
    assert evaluate("M8", "Negative Float", 1.0, thr).status is MetricStatus.FAIL


def test_result_carries_source_and_offenders() -> None:
    thr = Threshold(value=5.0, direction=Direction.LE, source=_SRC)
    offenders = (Offender(unique_id=7, kind="missing_predecessor", value=1.0),)
    result = evaluate("M1", "Logic", 9.0, thr, offenders=offenders, detail="2 of 22 tasks")
    assert result.status is MetricStatus.FAIL
    assert result.source == _SRC
    assert result.threshold == 5.0
    assert result.direction is Direction.LE
    assert result.offenders == offenders
    assert result.detail == "2 of 22 tasks"
    assert result.is_extension is False


def test_skipped_never_carries_a_measured_value() -> None:
    result = skipped("M10", "Resources", "no resource data on any task")
    assert result.status is MetricStatus.SKIPPED
    assert result.measured is None
    assert result.detail == "no resource data on any task"
