"""Executive-summary generator -- the LAST analysis-chain step (commandment 10).

Produces a plain-English narrative from a :class:`ScheduleAnalysis`: an overall
GREEN/YELLOW/RED health verdict, the DCMA integrity score, the forecast finish,
the critical and driving paths, the failing checks, and recommended actions.

Every number in the narrative is read directly from the analysis (H-DRIFT-1) --
the inference backend may only *rephrase* the narrative, never invent or alter a
number. The default :class:`NullInferenceBackend` returns the narrative verbatim,
so the summary is fully deterministic and testable with zero model.

The GREEN/YELLOW/RED banding is the tool's own health interpretation (a synthesis
layer, not reference-tool parity); its thresholds are defined once below.
"""

from __future__ import annotations

from enum import StrEnum

from schedule_forensics.analysis import ScheduleAnalysis
from schedule_forensics.inference import (
    DEFAULT_CLASSIFICATION,
    Classification,
    InferenceBackend,
    InferenceError,
    backend_from_env,
    select_backend,
)

_MINUTES_PER_DAY = 480.0

# Tool-original health-band thresholds (single source of truth). Not reference
# parity -- a synthesis over the DCMA integrity score. Any negative-float finding
# forces RED regardless of score (an unachievable date is a red flag).
_GREEN_MIN_SCORE = 90.0
_YELLOW_MIN_SCORE = 70.0


class HealthBand(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


def health_band(analysis: ScheduleAnalysis) -> HealthBand:
    """Classify overall health (tool synthesis; see module docstring)."""
    negative_float = any(
        m.metric_id == "DCMA-07" and m.status.value == "FAIL" for m in analysis.dcma
    )
    if analysis.health_score is None or negative_float:
        return HealthBand.RED
    if analysis.health_score >= _GREEN_MIN_SCORE:
        return HealthBand.GREEN
    if analysis.health_score >= _YELLOW_MIN_SCORE:
        return HealthBand.YELLOW
    return HealthBand.RED


def _recommendations(analysis: ScheduleAnalysis) -> list[str]:
    """One concrete action per failing DCMA check (keyed by metric name)."""
    actions: list[str] = []
    for metric in analysis.dcma:
        if metric.status.value != "FAIL":
            continue
        actions.append(f"Address '{metric.name}' ({metric.metric_id}): {metric.detail}")
    return actions


def build_narrative(analysis: ScheduleAnalysis) -> str:
    """Build the deterministic factual executive narrative (no model involved)."""
    band = health_band(analysis)
    lines: list[str] = [
        "SCHEDULE FORENSICS — EXECUTIVE SUMMARY",
        f"Overall schedule health: {band.value}.",
    ]

    if analysis.health_score is not None:
        lines.append(f"DCMA-14 integrity: {analysis.health_score:.1f}% of runnable checks pass.")
    else:
        lines.append("DCMA-14 integrity: not available (no runnable checks).")

    if analysis.project_finish is not None:
        days = analysis.project_finish / _MINUTES_PER_DAY
        lines.append(
            f"Forecast finish: {analysis.project_finish} working minutes "
            f"({days:.1f} working days) from project start."
        )
    else:
        lines.append(f"Forecast finish: NOT COMPUTED — {analysis.cpm_error}.")

    if analysis.critical_path:
        lines.append(
            "Critical path (UniqueIDs): "
            + ", ".join(str(uid) for uid in analysis.critical_path)
            + "."
        )
    if analysis.driving_chain:
        lines.append(
            "Driving path to completion (UniqueIDs): "
            + ", ".join(str(uid) for uid in analysis.driving_chain)
            + "."
        )

    # Earned-value indices (only when runnable; SKIPPED EV is omitted, not noise).
    ev_values = [
        f"{m.metric_id} {m.measured:.2f}"
        for m in analysis.performance_indices
        if m.status.value in ("PASS", "FAIL") and m.measured is not None
    ]
    if ev_values:
        lines.append(
            "Earned-value performance: "
            + "; ".join(ev_values)
            + " (1.0 = on plan; below 1.0 = behind schedule)."
        )

    if analysis.findings:
        lines.append(
            f"Failing DCMA checks ({len(analysis.findings)}): " + ", ".join(analysis.findings) + "."
        )
        lines.append("Recommended actions:")
        lines.extend(f"  - {action}" for action in _recommendations(analysis))
    else:
        lines.append("No DCMA checks are failing.")

    return "\n".join(lines)


def generate_executive_summary(
    analysis: ScheduleAnalysis,
    *,
    classification: Classification = DEFAULT_CLASSIFICATION,
    backend: InferenceBackend | None = None,
) -> str:
    """Generate the executive summary, routing through ``backend`` (LAW 1 gated).

    The factual narrative is built locally and deterministically; ``backend`` may
    only rephrase it. ``select_backend`` enforces that a non-local backend cannot
    be used under CUI (the default classification) -- it raises instead. When no
    ``backend`` is given the default comes from :func:`backend_from_env` -- a local
    OpenAI-compatible model when ``SF_LLM_BASE_URL`` is set (loopback only), else the
    deterministic NullInferenceBackend. If a configured local model is unreachable
    the summary falls back to the deterministic narrative (it never errors out the
    caller), since that narrative is the authoritative factual text either way.
    """
    chosen = backend if backend is not None else backend_from_env()
    select_backend(classification, chosen)  # fail closed before any data is used
    narrative = build_narrative(analysis)
    try:
        return chosen.summarize(narrative)
    except InferenceError:
        return narrative
