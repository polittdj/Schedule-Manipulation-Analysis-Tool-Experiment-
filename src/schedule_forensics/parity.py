"""Golden-file parity harness: check the tool's analysis against reference outputs.

LAW 2 (fidelity over speed): this tool exists only because its numbers match
Deltek Acumen Fuse, Steelray/SSI, and Microsoft Project on the same inputs. This
harness makes that claim *checkable*. A "golden case" pairs an input schedule
with a set of expected values that a reference tool produced for it; the harness
re-runs this tool on the same input and diffs every value within a stated
tolerance, recording which reference tool each expected number came from. Drift
is reported per check (H-DRIFT-1: every user-facing number traces to a computed
value, here verified against an external authority).

LAW 1 (data sovereignty): the harness only reads local files and computes
locally -- there is no network path. Real schedule inputs are CUI and must NOT
be committed: keep real golden cases in a LOCAL directory outside the repo and
point the runner at it (``scripts/parity_report.py --root``). The single in-repo
case is SELF-GENERATED from this tool's own output on a synthetic fixture -- a
regression baseline that guards the pipeline against unintended change. It is
explicitly **NOT** evidence of reference-tool parity (parity-honesty rule): until
a real Acumen/SSI/MS Project case is supplied, no parity claim is made.

Golden-case format (``<case_dir>/case.json``)::

    {
      "case": "<name>",
      "input": "<file relative to case dir>",   // .xml (MSPDI) | .xer | .json
      "reference_tool": "<who produced the expected values>",
      "notes": "<free text>",
      "checks": [
        {"metric": "project_finish_minutes", "expected": 2400, "tolerance": 0,
         "source": "<tool/version + locator>"},
        {"metric": "dcma:DCMA-04:status", "expected": "PASS", "source": "..."}
      ]
    }

Supported ``metric`` keys (resolved against :class:`ScheduleAnalysis`):

* ``project_finish_minutes`` / ``project_finish_days`` -- CPM project finish.
* ``health_score_percent`` -- DCMA integrity score.
* ``critical_path`` / ``driving_chain`` -- UniqueID lists (exact match).
* ``dcma:<ID>:<field>`` -- a DCMA metric's ``measured`` | ``status`` | ``threshold``.
* ``index:<ID>:<field>`` -- a performance index (``SPI`` / ``SPI(t)``) field.

Comparison rule: lists/strings are matched exactly (status compared as its name,
e.g. ``"PASS"``); numbers must be within ``tolerance`` (default ``0``). An unknown
metric key or a malformed case raises :class:`ParityError` -- the harness fails
loud rather than silently passing a typo (LAW 2).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from schedule_forensics.analysis import ScheduleAnalysis, analyze_schedule
from schedule_forensics.importers.msp_xml import parse_msp_xml_string
from schedule_forensics.importers.xer import parse_xer_string
from schedule_forensics.metrics_common import MetricResult
from schedule_forensics.schemas import Schedule

_MINUTES_PER_DAY: float = 480.0


class ParityError(Exception):
    """A malformed golden case or an unknown metric key (the harness fails loud)."""


@dataclass(frozen=True)
class ParityCheck:
    """One expected value in a golden case, with its tolerance and cited source."""

    metric: str
    expected: object
    tolerance: float
    source: str


@dataclass(frozen=True)
class GoldenCase:
    """A parity case: an input schedule plus the reference values expected from it."""

    name: str
    input_path: Path
    reference_tool: str
    notes: str
    checks: tuple[ParityCheck, ...]


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one :class:`ParityCheck` against the recomputed analysis."""

    metric: str
    expected: object
    actual: object
    source: str
    ok: bool
    detail: str


def load_case(case_dir: Path) -> GoldenCase:
    """Load and validate ``<case_dir>/case.json`` into a :class:`GoldenCase`.

    Raises :class:`ParityError` on a missing ``case.json``, a missing required
    key, a missing input file, or an empty ``checks`` list (fail loud -- a broken
    case must never quietly pass)."""
    spec_path = case_dir / "case.json"
    if not spec_path.is_file():
        raise ParityError(f"no case.json in {case_dir}")
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    try:
        name = str(data["case"])
        input_rel = str(data["input"])
        reference_tool = str(data["reference_tool"])
        raw_checks = data["checks"]
    except (KeyError, TypeError) as exc:
        raise ParityError(f"{spec_path}: malformed or missing required key {exc}") from exc

    input_path = (case_dir / input_rel).resolve()
    if not input_path.is_file():
        raise ParityError(f"{spec_path}: input file not found: {input_path}")

    checks: list[ParityCheck] = []
    for idx, raw in enumerate(raw_checks):
        try:
            metric = str(raw["metric"])
            expected = raw["expected"]
            source = str(raw["source"])
        except (KeyError, TypeError) as exc:
            raise ParityError(f"{spec_path}: check #{idx} malformed/missing key {exc}") from exc
        checks.append(
            ParityCheck(
                metric=metric,
                expected=expected,
                tolerance=float(raw.get("tolerance", 0.0)),
                source=source,
            )
        )
    if not checks:
        raise ParityError(f"{spec_path}: a golden case must define at least one check")

    return GoldenCase(
        name=name,
        input_path=input_path,
        reference_tool=reference_tool,
        notes=str(data.get("notes", "")),
        checks=tuple(checks),
    )


def _load_schedule(path: Path) -> Schedule:
    """Parse a golden-case input into a :class:`Schedule`, routed by extension.

    Supports the local text formats the suite can run hermetically: MS Project
    XML (MSPDI, the default), Primavera ``.xer``, and a serialized ``Schedule``
    JSON. A native binary ``.mpp`` must be exported to MS Project XML first (or
    converted via MPXJ) -- the harness does not shell out to a converter."""
    suffix = path.suffix.lower()
    if suffix == ".mpp":
        raise ParityError(
            f"{path}: native .mpp is not read directly here; export to MS Project XML "
            "(or convert via MPXJ) and point the case at the .xml."
        )
    text = path.read_text(encoding="utf-8")
    if suffix == ".xer":
        return parse_xer_string(text)
    if suffix == ".json":
        return Schedule.model_validate_json(text)
    return parse_msp_xml_string(text)


def _metric_field(metric: MetricResult, field: str) -> object:
    if field == "measured":
        return metric.measured
    if field == "status":
        return str(metric.status)
    if field == "threshold":
        return metric.threshold
    raise ParityError(f"unknown metric field '{field}' (use measured|status|threshold)")


def _resolve_metric(analysis: ScheduleAnalysis, key: str) -> object:
    """Resolve a golden-case ``metric`` key to the recomputed actual value."""
    if key == "project_finish_minutes":
        return analysis.project_finish
    if key == "project_finish_days":
        if analysis.project_finish is None:
            return None
        return analysis.project_finish / _MINUTES_PER_DAY
    if key == "health_score_percent":
        return analysis.health_score
    if key == "critical_path":
        return list(analysis.critical_path)
    if key == "driving_chain":
        return list(analysis.driving_chain)

    parts = key.split(":")
    if len(parts) == 3 and parts[0] in ("dcma", "index"):
        pool = analysis.dcma if parts[0] == "dcma" else analysis.performance_indices
        metric_id, field = parts[1], parts[2]
        for metric in pool:
            if metric.metric_id == metric_id:
                return _metric_field(metric, field)
        raise ParityError(f"no metric with id '{metric_id}' for key '{key}'")

    raise ParityError(f"unknown metric key '{key}'")


def _compare(check: ParityCheck, actual: object) -> CheckResult:
    """Compare one expected value to the actual (tolerance for numbers, exact else)."""
    expected = check.expected
    if isinstance(expected, list):
        actual_cmp: object = list(actual) if isinstance(actual, (list, tuple)) else actual
        ok = actual_cmp == expected
    elif isinstance(expected, bool):
        ok = actual == expected
    elif isinstance(expected, (int, float)):
        ok = (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and abs(float(actual) - float(expected)) <= check.tolerance
        )
    else:
        ok = str(actual) == str(expected)

    tol = f" +/-{check.tolerance}" if isinstance(expected, (int, float)) else ""
    detail = (
        f"{check.metric}: expected {expected!r}{tol} [{check.source}]; "
        f"got {actual!r} -> {'OK' if ok else 'DRIFT'}"
    )
    return CheckResult(
        metric=check.metric,
        expected=expected,
        actual=actual,
        source=check.source,
        ok=ok,
        detail=detail,
    )


def evaluate_case(case: GoldenCase) -> tuple[CheckResult, ...]:
    """Re-run the analysis on the case input and compare every check."""
    analysis = analyze_schedule(_load_schedule(case.input_path))
    return tuple(_compare(check, _resolve_metric(analysis, check.metric)) for check in case.checks)


def discover_cases(root: Path) -> list[Path]:
    """Return every case directory under *root* (those containing ``case.json``).

    A missing *root* yields an empty list (not an error): the suite simply has no
    golden cases to run until one is added."""
    if not root.is_dir():
        return []
    return sorted(spec.parent for spec in root.glob("*/case.json"))


def format_report(case: GoldenCase, results: Sequence[CheckResult]) -> str:
    """Render a human-readable per-case parity report."""
    n_ok = sum(1 for r in results if r.ok)
    lines = [
        f"Parity case: {case.name}",
        f"  input:     {case.input_path}",
        f"  reference: {case.reference_tool}",
    ]
    if case.notes:
        lines.append(f"  notes:     {case.notes}")
    lines.append(f"  {n_ok}/{len(results)} checks within tolerance")
    lines.extend(f"    [{'OK   ' if r.ok else 'DRIFT'}] {r.detail}" for r in results)
    return "\n".join(lines)
