"""Single-schedule analysis composition (the integration backbone for reports/UI).

Runs the CPM once and feeds that one result to every consumer -- the DCMA-14
checks (structural + progress) and the driving-path trace -- then derives an
integrity/health score from the DCMA outcomes. If the network cannot be scheduled
(a logic cycle, or a deferred ALAP/MSO/MFO constraint), the CPM-dependent outputs
degrade safely: ``project_finish`` is ``None``, the driving chain is empty, the
CPM-dependent DCMA checks come back SKIPPED with the error surfaced -- nothing is
fabricated (LAW 2). The structure-only checks still run.

Health score (integrity): the share, in ``[0, 100]``, of *runnable* DCMA metrics
(PASS or FAIL -- SKIPPED metrics are excluded) that PASS. It is derived from the
real pass count, so ANY failing runnable metric pulls it below 100 -- the
"always-100" regression guard the prior build called out. ``None`` when no metric
is runnable.
"""

from __future__ import annotations

from dataclasses import dataclass

from schedule_forensics.cpm import CPMError, CPMResult, TaskTiming, compute_cpm
from schedule_forensics.dcma_checks import run_structural_checks
from schedule_forensics.dcma_progress import run_progress_checks
from schedule_forensics.driving_path import analyze_driving_path
from schedule_forensics.metrics_common import MetricResult, MetricStatus
from schedule_forensics.performance_indices import run_performance_indices
from schedule_forensics.schemas import Schedule


@dataclass(frozen=True)
class ScheduleAnalysis:
    """Composed analysis of a single schedule version.

    ``project_finish`` and ``timings`` are ``None``/empty when the CPM could not
    be computed (``cpm_error`` then carries the reason). ``dcma`` is all 14 checks
    in id order (DCMA-01..14). ``health_score`` is the integrity score described in
    the module docstring; ``findings`` names the runnable DCMA metrics that FAILED.

    ``performance_indices`` holds the earned-value indices (SPI, SPI(t)). They are
    SKIPPED unless the schedule carries earned-value data (``budgeted_cost`` +
    baseline dates), and are deliberately kept OUT of ``health_score``/``findings``
    -- those stay DCMA-14-only, so an EV index never silently moves the DCMA
    integrity score.
    """

    project_finish: int | None
    critical_path: tuple[int, ...]
    timings: dict[int, TaskTiming]
    driving_chain: tuple[int, ...]
    dcma: tuple[MetricResult, ...]
    health_score: float | None
    findings: tuple[str, ...]
    cpm_error: str | None
    performance_indices: tuple[MetricResult, ...] = ()


def analyze_schedule(schedule: Schedule) -> ScheduleAnalysis:
    """Compose the CPM, the full DCMA-14 assessment, and the driving path."""
    cpm: CPMResult | None
    cpm_error: str | None = None
    try:
        cpm = compute_cpm(schedule)
    except CPMError as exc:
        cpm = None
        cpm_error = str(exc)

    # The run_* functions accept the (possibly None) CPM result and SKIP their
    # CPM-dependent checks when it is unavailable -- a single source of truth for
    # that degradation, so we never duplicate the skip logic here.
    dcma = (*run_structural_checks(schedule, cpm), *run_progress_checks(schedule, cpm))

    driving_chain = analyze_driving_path(schedule, cpm).driving_chain if cpm is not None else ()

    runnable = [m for m in dcma if m.status in (MetricStatus.PASS, MetricStatus.FAIL)]
    passed = [m for m in runnable if m.status is MetricStatus.PASS]
    health_score = 100.0 * len(passed) / len(runnable) if runnable else None
    findings = tuple(m.name for m in runnable if m.status is MetricStatus.FAIL)

    # Earned-value indices: independent of the DCMA integrity score (kept out of
    # health_score/findings on purpose). SKIPPED unless EV data is present.
    performance_indices = run_performance_indices(schedule)

    return ScheduleAnalysis(
        project_finish=cpm.project_finish if cpm is not None else None,
        critical_path=cpm.critical_path if cpm is not None else (),
        timings=cpm.timings if cpm is not None else {},
        driving_chain=driving_chain,
        dcma=dcma,
        health_score=health_score,
        findings=findings,
        cpm_error=cpm_error,
        performance_indices=performance_indices,
    )
