"""Schedule Risk Analysis (SRA) via Monte Carlo over task-duration uncertainty.

This module answers the forensic question "given uncertainty in each activity's
duration, what is the probability distribution of the project finish date, and
how often does each activity land on the critical path?" -- the standard
Monte-Carlo SRA that Deltek Acumen Fuse (the "Risk" tab) and Primavera Risk
Analysis produce. Each iteration samples a duration for every non-summary
activity from a three-point (BetaPERT) distribution, re-runs the frozen CPM
engine, and records the resulting project finish and critical-path membership.
Aggregating thousands of iterations yields finish-date percentiles (P50/P80/P95)
and a per-activity *criticality index* (the fraction of iterations on the
critical path).

Units: the project-finish distribution is on the same INTEGER WORKING-MINUTE
axis as :mod:`schedule_forensics.cpm` (480 working minutes == one 8-hour day,
offset from ``Schedule.project_start``). No wall-clock dates are introduced here;
a caller converts a percentile offset to a date via ``cpm.offset_to_datetime``.

Sources (Law 2 / parity-honesty):

* The Monte-Carlo SRA *method* (sample durations -> rerun CPM -> aggregate
  finish distribution + criticality index) is standard quantitative-scheduling
  practice, mirrored by Acumen Fuse and Primavera Risk Analysis. REFERENCES.md
  key: ``SRA-MONTE-CARLO``; cited in practice, exact page-anchor
  **source-pending**.
* **BetaPERT** is the classic three-point distribution: with mode ``M`` in
  ``[O, P]`` the shape parameters are ``a = 1 + 4*(M-O)/(P-O)`` and
  ``b = 1 + 4*(P-M)/(P-O)`` and a draw is ``O + Beta(a, b)*(P-O)`` (the lambda=4
  PERT weighting). REFERENCES.md key: ``BETA-PERT``; cited in practice,
  page-anchor **source-pending**.
* The default three-point *multipliers* (O = 0.75*D, M = D, P = 1.5*D) are the
  **tool's default heuristic, not a reference-tool value** -- they are
  configurable via the ``three_point`` callback. This default is therefore
  ``source-pending`` and is documented as a tool default, never claimed as
  parity. (In a real engagement the analyst supplies risk ranges per activity.)

Parity status: Monte-Carlo SRA itself is a reference-tool capability and is NOT
flagged as a tool-original extension. The specific default duration-spread
heuristic *is* the tool's own default and is labelled as such. Because the
distribution is over duration uncertainty only (no logic/calendar/resource risk
modelling yet), this is a documented scope, not a silent limitation.

Determinism: every random draw comes from a single ``random.Random(seed)``, and
activities are sampled in ascending ``unique_id`` order, so a given ``seed``
reproduces an identical :class:`SRAResult` exactly (no "approximately" --
H-DRIFT-1). If the *base* schedule cannot be scheduled, the underlying
``CPMError`` propagates unchanged; the SRA never fabricates a result.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from schedule_forensics.cpm import compute_cpm
from schedule_forensics.schemas import Schedule, Task

# A three-point estimator: given a non-summary task, return (optimistic,
# most_likely, pessimistic) durations in working minutes. ``most_likely`` must
# lie in ``[optimistic, pessimistic]``. The default below is a TOOL HEURISTIC.
ThreePoint = Callable[[Task], tuple[float, float, float]]

# Default three-point heuristic multipliers (TOOL DEFAULT, configurable -- NOT a
# reference-tool value). Defined once here as the single source of truth.
_DEFAULT_OPTIMISTIC_FACTOR = 0.75
_DEFAULT_PESSIMISTIC_FACTOR = 1.5

# The PERT weighting on the mode (the "4" in BetaPERT). Standard practice.
_PERT_LAMBDA = 4.0


def default_three_point(task: Task) -> tuple[float, float, float]:
    """The tool's DEFAULT three-point estimate for a task (heuristic, not parity).

    ``O = 0.75 * D``, ``M = D``, ``P = 1.5 * D`` where ``D`` is the task's
    deterministic ``duration_minutes``. These multipliers are the tool's default
    and are configurable via ``run_sra(..., three_point=...)``; the Monte-Carlo
    SRA method around them is standard practice (see the module docstring).
    """
    d = float(task.duration_minutes)
    return (_DEFAULT_OPTIMISTIC_FACTOR * d, d, _DEFAULT_PESSIMISTIC_FACTOR * d)


@dataclass(frozen=True)
class SRAResult:
    """The aggregated outcome of a Monte-Carlo Schedule Risk Analysis.

    Every finish quantity is an INTEGER WORKING-MINUTE offset from
    ``Schedule.project_start`` (the same axis as :mod:`schedule_forensics.cpm`),
    except ``mean_finish`` which is the floating-point mean of those offsets.

    Fields:

    * ``iterations`` -- number of Monte-Carlo trials actually run.
    * ``p50`` / ``p80`` / ``p95`` -- nearest-rank percentiles of the
      project-finish-offset distribution (see :func:`_nearest_rank_percentile`
      for the exact, interpolation-free rule). ``p50 <= p80 <= p95`` always.
    * ``mean_finish`` -- arithmetic mean of the finish offsets (float minutes).
    * ``deterministic_finish`` -- the un-sampled CPM ``project_finish`` of the
      base schedule, for reference (the "deterministic" answer SRA brackets).
    * ``criticality_index`` -- per non-summary ``unique_id``, the fraction in
      ``[0.0, 1.0]`` of iterations in which the activity was on the critical
      path (``total_float <= 0``). Every non-summary task is present (a task on
      no iteration's critical path maps to ``0.0``).
    * ``finish_histogram`` -- a deterministic, sorted tuple of
      ``(finish_offset, count)`` pairs covering every finish offset observed
      (the empirical distribution; sums to ``iterations``).
    """

    iterations: int
    p50: int
    p80: int
    p95: int
    mean_finish: float
    deterministic_finish: int
    criticality_index: dict[int, float]
    finish_histogram: tuple[tuple[int, int], ...] = field(default_factory=tuple)


def _pert_beta_params(o: float, m: float, p: float) -> tuple[float, float]:
    """BetaPERT shape parameters ``(a, b)`` for optimistic/mode/pessimistic.

    ``a = 1 + lambda*(M-O)/(P-O)``, ``b = 1 + lambda*(P-M)/(P-O)`` with the
    standard ``lambda = 4``. The caller guarantees ``P > O`` (the degenerate
    ``P == O`` case is handled before this is called), so the divisor is
    positive and ``a, b >= 1``.
    """
    span = p - o
    a = 1.0 + _PERT_LAMBDA * (m - o) / span
    b = 1.0 + _PERT_LAMBDA * (p - m) / span
    return a, b


def _sample_duration(rng: random.Random, o: float, m: float, p: float) -> int:
    """Draw one BetaPERT duration sample (rounded to int working minutes).

    Degenerate guard: when ``p <= o`` there is zero variance, so the sample is
    exactly ``o`` (== ``m`` == ``p``) and ``betavariate`` is NOT called (it would
    divide by a zero span). Otherwise draw ``x = Beta(a, b)`` and map it onto the
    range as ``o + x*(p - o)``. The result is clamped to ``>= 0`` so a path%
    estimator can never produce a negative duration the schema would reject.
    """
    if p <= o:
        return max(int(round(o)), 0)
    a, b = _pert_beta_params(o, m, p)
    x = rng.betavariate(a, b)
    sample = o + x * (p - o)
    return max(int(round(sample)), 0)


def _nearest_rank_percentile(sorted_values: Sequence[int], pct: float) -> int:
    """Nearest-rank percentile of an ascending, non-empty ``sorted_values``.

    Uses the *nearest-rank* method (no interpolation, exact and reproducible):
    the ordinal rank is ``ceil(pct/100 * N)`` clamped to ``[1, N]`` and the
    percentile is the value at that 1-based rank (i.e. index ``rank - 1``). This
    returns an actual observed sample, which keeps every reported percentile an
    exact, traceable integer (H-DRIFT-1) rather than an interpolated estimate.
    """
    n = len(sorted_values)
    rank = math.ceil(pct / 100.0 * n)
    rank = max(1, min(rank, n))
    return sorted_values[rank - 1]


def run_sra(
    schedule: Schedule,
    *,
    iterations: int = 5000,
    seed: int = 12345,
    three_point: ThreePoint | None = None,
) -> SRAResult:
    """Run a Monte-Carlo Schedule Risk Analysis over task-duration uncertainty.

    For each of ``iterations`` trials, sample a BetaPERT duration for every
    non-summary activity (from ``three_point`` or :func:`default_three_point`),
    build a duration-perturbed copy of ``schedule``, run
    :func:`~schedule_forensics.cpm.compute_cpm`, and record the resulting
    ``project_finish`` offset and critical-path membership. Returns the
    aggregated :class:`SRAResult`.

    Determinism: all draws come from a single ``random.Random(seed)`` and tasks
    are sampled in ascending ``unique_id`` order, so the same ``seed`` (and same
    schedule + estimator) reproduces an identical result exactly.

    Raises:
        ValueError: if ``iterations < 1``.
        CPMError: whatever :func:`compute_cpm` raises on an unschedulable base
            network (a logic cycle, or a deferred constraint). The base schedule
            is validated up front, so the error surfaces before any sampling and
            is never masked by an "averaged" result.
    """
    if iterations < 1:
        raise ValueError("run_sra: iterations must be >= 1")

    estimator = three_point if three_point is not None else default_three_point

    # Validate the base network FIRST: if it cannot be scheduled, propagate the
    # CPMError immediately rather than discover it mid-sampling (or worse, hide
    # it). This also gives us the reference deterministic finish.
    base_result = compute_cpm(schedule)
    deterministic_finish = base_result.project_finish

    # Fixed, deterministic sampling order: non-summary tasks by ascending
    # unique_id. The summary tasks are passed through unchanged (they carry no
    # duration in the network -- the CPM excludes them).
    sampled_tasks = sorted(
        (t for t in schedule.tasks if not t.is_summary), key=lambda t: t.unique_id
    )
    # Pre-compute each sampled task's three-point estimate once (estimators are
    # pure functions of the deterministic task; only the random draw varies).
    estimates: list[tuple[Task, float, float, float]] = []
    for task in sampled_tasks:
        o, m, p = estimator(task)
        estimates.append((task, o, m, p))

    rng = random.Random(seed)

    finish_offsets: list[int] = []
    # Count of critical-path appearances per sampled unique_id (0 for every
    # sampled task up front, so off-path tasks report exactly 0.0).
    critical_counts: dict[int, int] = {t.unique_id: 0 for t in sampled_tasks}
    histogram: dict[int, int] = {}

    for _ in range(iterations):
        # Replace each non-summary task's duration with a fresh sample. Tasks are
        # frozen (pydantic v2) -> rebuild copies; never mutate in place.
        new_tasks: list[Task] = []
        sample_by_id: dict[int, int] = {}
        for task, o, m, p in estimates:
            dur = _sample_duration(rng, o, m, p)
            sample_by_id[task.unique_id] = dur
        for task in schedule.tasks:
            if task.is_summary:
                new_tasks.append(task)
            else:
                new_tasks.append(
                    task.model_copy(update={"duration_minutes": sample_by_id[task.unique_id]})
                )
        trial_schedule = schedule.model_copy(update={"tasks": tuple(new_tasks)})

        trial = compute_cpm(trial_schedule)
        finish = trial.project_finish
        finish_offsets.append(finish)
        histogram[finish] = histogram.get(finish, 0) + 1
        for tid in trial.critical_path:
            if tid in critical_counts:  # ignore any summary (none reach here)
                critical_counts[tid] += 1

    finish_offsets.sort()
    mean_finish = sum(finish_offsets) / iterations
    criticality_index = {tid: count / iterations for tid, count in critical_counts.items()}
    finish_histogram = tuple(sorted(histogram.items()))

    return SRAResult(
        iterations=iterations,
        p50=_nearest_rank_percentile(finish_offsets, 50.0),
        p80=_nearest_rank_percentile(finish_offsets, 80.0),
        p95=_nearest_rank_percentile(finish_offsets, 95.0),
        mean_finish=mean_finish,
        deterministic_finish=deterministic_finish,
        criticality_index=criticality_index,
        finish_histogram=finish_histogram,
    )
