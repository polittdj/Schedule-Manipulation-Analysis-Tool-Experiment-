"""Golden-file parity harness tests.

Two layers:

1. Every golden case under ``tests/fixtures/golden/`` is loaded, recomputed, and
   asserted within tolerance (the in-repo case is the self-generated regression
   baseline -- it catches unintended pipeline drift).
2. Harness unit tests prove the machinery is NON-VACUOUS: a perturbed expected
   value MUST be reported as drift, an unknown metric key MUST raise, and a
   malformed case MUST raise (H-VACUOUS-TEST / qa-auditor: a test that cannot
   fail is worthless).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schedule_forensics.parity import (
    GoldenCase,
    ParityCheck,
    ParityError,
    discover_cases,
    evaluate_case,
    load_case,
)

_GOLDEN_ROOT = Path(__file__).parent / "fixtures" / "golden"
_FIXTURE_XML = Path(__file__).parent / "fixtures" / "msp_xml" / "simple_network.xml"


# ── Layer 1: real golden cases ────────────────────────────────────────────────


@pytest.mark.parametrize("case_dir", discover_cases(_GOLDEN_ROOT), ids=lambda p: p.name)
def test_golden_case_within_tolerance(case_dir: Path) -> None:
    """Each golden case recomputes within tolerance of its expected values."""
    case = load_case(case_dir)
    results = evaluate_case(case)
    assert results, f"{case.name}: a case must define at least one check"
    drifted = [r.detail for r in results if not r.ok]
    assert not drifted, f"{case.name}: parity drift:\n" + "\n".join(drifted)


def test_self_baseline_case_is_present() -> None:
    """The in-repo self-regression case ships and is discovered (guards CI coverage)."""
    names = {p.name for p in discover_cases(_GOLDEN_ROOT)}
    assert "simple_network_self" in names


def test_self_baseline_is_not_claimed_as_parity() -> None:
    """LAW 2 parity-honesty: the in-repo case must NOT claim reference-tool parity."""
    case = load_case(_GOLDEN_ROOT / "simple_network_self")
    assert "NOT" in case.reference_tool.upper() or "self" in case.reference_tool.lower()


# ── Layer 2: harness is non-vacuous ───────────────────────────────────────────


def _case(metric: str, expected: object, tolerance: float = 0.0) -> GoldenCase:
    return GoldenCase(
        name="synthetic",
        input_path=_FIXTURE_XML,
        reference_tool="unit-test",
        notes="",
        checks=(ParityCheck(metric=metric, expected=expected, tolerance=tolerance, source="ut"),),
    )


def test_matching_value_passes() -> None:
    (result,) = evaluate_case(_case("project_finish_minutes", 2400))
    assert result.ok
    assert result.actual == 2400


def test_perturbed_value_is_reported_as_drift() -> None:
    """A wrong expected value MUST fail -- the harness can actually detect drift."""
    (result,) = evaluate_case(_case("project_finish_minutes", 9999))
    assert not result.ok
    assert "DRIFT" in result.detail


def test_tolerance_band_is_honoured() -> None:
    # Actual health score is 72.7272...%; within a 0.05 band of 72.70, outside 0.001.
    assert evaluate_case(_case("health_score_percent", 72.70, tolerance=0.05))[0].ok
    assert not evaluate_case(_case("health_score_percent", 72.70, tolerance=0.001))[0].ok


def test_status_and_list_keys_match_exactly() -> None:
    assert evaluate_case(_case("dcma:DCMA-01:status", "FAIL"))[0].ok
    assert not evaluate_case(_case("dcma:DCMA-01:status", "PASS"))[0].ok
    assert evaluate_case(_case("critical_path", [1, 2, 4]))[0].ok
    assert not evaluate_case(_case("critical_path", [1, 2, 3]))[0].ok


def test_unknown_metric_key_raises() -> None:
    with pytest.raises(ParityError, match="unknown metric key"):
        evaluate_case(_case("not_a_real_metric", 1))


def test_unknown_dcma_id_raises() -> None:
    with pytest.raises(ParityError, match="no metric with id"):
        evaluate_case(_case("dcma:DCMA-99:status", "PASS"))


def test_load_case_missing_json_raises(tmp_path: Path) -> None:
    with pytest.raises(ParityError, match="no case.json"):
        load_case(tmp_path)


def test_load_case_missing_input_raises(tmp_path: Path) -> None:
    (tmp_path / "case.json").write_text(
        json.dumps(
            {
                "case": "x",
                "input": "nope.xml",
                "reference_tool": "ut",
                "checks": [{"metric": "project_finish_minutes", "expected": 1, "source": "ut"}],
            }
        )
    )
    with pytest.raises(ParityError, match="input file not found"):
        load_case(tmp_path)


def test_load_case_empty_checks_raises(tmp_path: Path) -> None:
    (tmp_path / "input.xml").write_text(_FIXTURE_XML.read_text())
    (tmp_path / "case.json").write_text(
        json.dumps({"case": "x", "input": "input.xml", "reference_tool": "ut", "checks": []})
    )
    with pytest.raises(ParityError, match="at least one check"):
        load_case(tmp_path)
