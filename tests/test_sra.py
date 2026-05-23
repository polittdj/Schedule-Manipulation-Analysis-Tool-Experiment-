"""Monte-Carlo SRA tests against independently hand-reasoned expectations.

Every assertion here is derived from the math and the network by hand (shown in
each test's comment), never read back from ``run_sra``'s own output -- that is
what makes the suite a fidelity proof and not a tautology (LAW 2 /
H-VACUOUS-TEST). The calendar is the default 480 working minutes/day, so 1 day
== 480 working minutes, and every finish quantity is an integer working-minute
offset on the same axis as :mod:`schedule_forensics.cpm`.

The anchor is the *zero-variance* case: a ``three_point`` returning ``(D, D, D)``
makes O == M == P, so the degenerate guard returns exactly ``D`` on every draw
(``betavariate`` is never called). Then every iteration reproduces the base CPM,
so ``p50 == p80 == p95 == mean == deterministic_finish`` EXACTLY -- an integer
identity, with no "approximately" (H-DRIFT-1).

Percentile rule under test: NEAREST-RANK (no interpolation). For a sorted sample
of size ``N`` the ordinal rank is ``ceil(pct/100 * N)`` clamped to ``[1, N]`` and
the percentile is the value at 1-based ``rank`` (index ``rank - 1``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pytest

from schedule_forensics.cpm import CPMError
from schedule_forensics.schemas import ConstraintType, Relation, Schedule, Task
from schedule_forensics.sra import (
    SRAResult,
    _nearest_rank_percentile,
    _pert_beta_params,
    _sample_duration,
    default_three_point,
    run_sra,
)

_START = dt.datetime(2025, 1, 6, 8)  # a Monday


def _sched(tasks: Iterable[Task], relations: Iterable[Relation] = ()) -> Schedule:
    return Schedule(name="t", project_start=_START, tasks=tuple(tasks), relations=tuple(relations))


def _zero_variance(task: Task) -> tuple[float, float, float]:
    """Three-point estimator with O == M == P == D -> the degenerate (no-draw) case."""
    d = float(task.duration_minutes)
    return (d, d, d)


# --------------------------------------------------------------------------- #
# Closed-form helpers: BetaPERT params, the degenerate guard, nearest-rank.
# --------------------------------------------------------------------------- #


def test_pert_beta_params_hand_values() -> None:
    # O=360, M=480, P=720 (the default heuristic for D=480). span=360.
    #   a = 1 + 4*(480-360)/360 = 1 + 4*(120/360) = 1 + 4/3 = 7/3
    #   b = 1 + 4*(720-480)/360 = 1 + 4*(240/360) = 1 + 8/3 = 11/3
    a, b = _pert_beta_params(360.0, 480.0, 720.0)
    assert a == pytest.approx(7.0 / 3.0)
    assert b == pytest.approx(11.0 / 3.0)


def test_pert_beta_params_symmetric_mode_gives_equal_shapes() -> None:
    # Mode centred (M is the midpoint of O,P) => a == b == 1 + 4*0.5 = 3.
    a, b = _pert_beta_params(0.0, 50.0, 100.0)
    assert a == pytest.approx(3.0)
    assert b == pytest.approx(3.0)


def test_sample_duration_degenerate_returns_o_without_drawing() -> None:
    # P == O (zero variance): the guard returns round(O) and must NOT touch the
    # RNG. We assert non-consumption by passing an RNG whose first draw we capture
    # separately: identical RNGs must remain in lockstep after a degenerate call.
    import random  # noqa: PLC0415  (local: only this test needs a raw RNG)

    untouched = random.Random(123)
    probe = random.Random(123)
    out = _sample_duration(untouched, 480.0, 480.0, 480.0)
    assert out == 480
    # If betavariate had been called, ``untouched`` would have advanced.
    assert untouched.betavariate(2.0, 3.0) == probe.betavariate(2.0, 3.0)


def test_sample_duration_degenerate_rounds_and_floors_at_zero() -> None:
    import random  # noqa: PLC0415

    rng = random.Random(0)
    assert _sample_duration(rng, 12.4, 12.4, 12.4) == 12  # round-half handled by round()
    assert _sample_duration(rng, 0.0, 0.0, 0.0) == 0  # never negative


def test_sample_duration_in_range_for_nondegenerate() -> None:
    import random  # noqa: PLC0415

    rng = random.Random(99)
    o, m, p = 100.0, 200.0, 500.0
    for _ in range(200):
        s = _sample_duration(rng, o, m, p)
        # A BetaPERT draw maps Beta(0..1) onto [O, P]; rounding cannot escape it
        # by more than half a minute, so floor/ceil of O/P bound it.
        assert int(round(o)) <= s <= int(round(p))


def test_nearest_rank_percentile_hand_values() -> None:
    # N=10 ascending. rank(p) = ceil(p/100 * 10), clamp [1,10], value at rank-1.
    #   p50 -> ceil(5.0)=5  -> values[4] = 50
    #   p80 -> ceil(8.0)=8  -> values[7] = 80
    #   p95 -> ceil(9.5)=10 -> values[9] = 100
    #   p100-> ceil(10.0)=10-> values[9] = 100 ; p0 clamps to rank 1 -> values[0]=10
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert _nearest_rank_percentile(values, 50.0) == 50
    assert _nearest_rank_percentile(values, 80.0) == 80
    assert _nearest_rank_percentile(values, 95.0) == 100
    assert _nearest_rank_percentile(values, 100.0) == 100
    assert _nearest_rank_percentile(values, 0.0) == 10


def test_nearest_rank_percentile_returns_observed_sample() -> None:
    # Nearest-rank always returns an ACTUAL element (no interpolated 55, etc.).
    values = [3, 3, 7, 7, 7, 9]
    for pct in (10.0, 25.0, 50.0, 75.0, 90.0, 99.0):
        assert _nearest_rank_percentile(values, pct) in set(values)


def test_default_three_point_multipliers() -> None:
    # Tool-default heuristic: O=0.75D, M=D, P=1.5D. D=800 -> (600, 800, 1200).
    o, m, p = default_three_point(Task(unique_id=1, name="A", duration_minutes=800))
    assert (o, m, p) == (600.0, 800.0, 1200.0)


# --------------------------------------------------------------------------- #
# The zero-variance ANCHOR: an exact integer identity, fully hand-checked.
# --------------------------------------------------------------------------- #


def test_zero_variance_collapses_distribution_to_deterministic() -> None:
    # Network: A(1000) -> C(ms); B(200) -> C(ms).  (C is a finish milestone.)
    # Deterministic CPM early dates (default calendar):
    #   A es0 ef1000; B es0 ef200; C es1000 ef1000. project_finish = 1000.
    # Floats: A & C have total_float 0 (critical); B has 1000-200 = 800 free, off
    # the path -> NOT critical.
    # With three_point=(D,D,D) every iteration reproduces this exact schedule, so
    # EVERY finish offset == 1000. Hence p50==p80==p95==mean==deterministic==1000,
    # the criticality of A and C is 1.0, and B (the off-path slack task) is 0.0.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=1000),
            Task(unique_id=2, name="B", duration_minutes=200),
            Task(unique_id=3, name="C", duration_minutes=0, is_milestone=True),
        ],
        [
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=3),
        ],
    )
    result = run_sra(schedule, iterations=250, seed=9, three_point=_zero_variance)

    assert result.iterations == 250
    assert result.deterministic_finish == 1000
    assert result.p50 == 1000
    assert result.p80 == 1000
    assert result.p95 == 1000
    assert result.mean_finish == 1000.0  # exact float identity, no rounding noise
    # Distribution is a single spike at 1000 over all iterations.
    assert result.finish_histogram == ((1000, 250),)
    # Criticality: A and the finish milestone C are always on the path; B never.
    assert result.criticality_index == {1: 1.0, 2: 0.0, 3: 1.0}


def test_zero_variance_single_task_finish_equals_duration() -> None:
    # One activity, no logic: finish offset == its duration on every iteration.
    # D=480 -> deterministic finish 480; zero-variance keeps every draw at 480.
    schedule = _sched([Task(unique_id=7, name="solo", duration_minutes=480)])
    result = run_sra(schedule, iterations=64, seed=1, three_point=_zero_variance)
    assert (result.p50, result.p80, result.p95) == (480, 480, 480)
    assert result.mean_finish == 480.0
    assert result.deterministic_finish == 480
    assert result.criticality_index == {7: 1.0}


# --------------------------------------------------------------------------- #
# Distributional properties under REAL variance (default heuristic).
# --------------------------------------------------------------------------- #


def _linear_chain() -> Schedule:
    # A(960) -> B(1440) -> C(480): deterministic finish 960+1440+480 = 2880,
    # whole chain critical (every task total_float 0).
    return _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=960),
            Task(unique_id=2, name="B", duration_minutes=1440),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=3),
        ],
    )


def test_percentiles_are_monotonic_under_variance() -> None:
    # With the default 0.75/1.5 spread the finish distribution is non-degenerate;
    # nearest-rank percentiles must be non-decreasing for ANY sample.
    result = run_sra(_linear_chain(), iterations=3000, seed=2024)
    assert result.p50 <= result.p80 <= result.p95
    # Variance is genuinely present (the run is not secretly degenerate): more
    # than one distinct finish offset was observed.
    assert len(result.finish_histogram) > 1
    # The histogram is a complete, sorted partition of the iterations.
    assert sum(count for _off, count in result.finish_histogram) == result.iterations
    assert list(result.finish_histogram) == sorted(result.finish_histogram)


def test_criticality_index_within_unit_interval_and_keyed_by_nonsummary() -> None:
    # Every criticality value is a probability in [0, 1]; summary tasks are NOT
    # keys (they are excluded from the network), non-summary tasks ALL are.
    schedule = _sched(
        [
            Task(unique_id=10, name="Phase", duration_minutes=0, is_summary=True),
            Task(unique_id=1, name="A", duration_minutes=960),
            Task(unique_id=2, name="B", duration_minutes=480),
            Task(unique_id=3, name="C", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=1, successor_id=3),
        ],
    )
    result = run_sra(schedule, iterations=1500, seed=55)
    assert set(result.criticality_index) == {1, 2, 3}  # summary 10 absent
    assert all(0.0 <= ci <= 1.0 for ci in result.criticality_index.values())
    # A precedes both B and C, so A is on the path in EVERY iteration -> 1.0.
    assert result.criticality_index[1] == 1.0


def test_mean_lies_between_observed_extremes() -> None:
    # The mean of the finish offsets must fall within the observed support; this
    # also pins mean_finish to the histogram rather than an unrelated number.
    result = run_sra(_linear_chain(), iterations=1200, seed=7)
    offsets = [off for off, _count in result.finish_histogram]
    assert min(offsets) <= result.mean_finish <= max(offsets)
    # Recompute the mean independently from the histogram and match it exactly.
    total = sum(off * count for off, count in result.finish_histogram)
    assert result.mean_finish == total / result.iterations


# --------------------------------------------------------------------------- #
# Determinism / reproducibility.
# --------------------------------------------------------------------------- #


def test_same_seed_reproduces_identical_result() -> None:
    schedule = _linear_chain()
    a = run_sra(schedule, iterations=400, seed=42)
    b = run_sra(schedule, iterations=400, seed=42)
    assert a == b
    assert isinstance(a, SRAResult)


def test_different_seed_changes_the_sample() -> None:
    # A different seed draws different durations, so at least one aggregate moves.
    # (Asserted as inequality of the whole result, which cannot hold vacuously
    # because the zero-variance path is not used here.)
    schedule = _linear_chain()
    a = run_sra(schedule, iterations=400, seed=42)
    c = run_sra(schedule, iterations=400, seed=43)
    assert a != c


# --------------------------------------------------------------------------- #
# Perturbation discipline (H-VACUOUS-TEST): widening spread must move p95.
# --------------------------------------------------------------------------- #


def test_widening_pessimistic_spread_increases_p95() -> None:
    # Single task so the finish offset == the sampled duration directly; this
    # isolates the effect of the duration distribution from any logic.
    # D=1000. BEFORE: P=1.5D=1500. AFTER: P=3.0D=3000 (wider right tail, same
    # O and M). Drawing from the SAME seed, the wider pessimistic bound must push
    # the upper percentile strictly higher. Asserting BOTH the before value and
    # the strict increase is what proves the spread is actually being consumed.
    schedule = _sched([Task(unique_id=1, name="A", duration_minutes=1000)])

    def narrow(task: Task) -> tuple[float, float, float]:
        d = float(task.duration_minutes)
        return (0.75 * d, d, 1.5 * d)  # P = 1500

    def wide(task: Task) -> tuple[float, float, float]:
        d = float(task.duration_minutes)
        return (0.75 * d, d, 3.0 * d)  # P = 3000

    before = run_sra(schedule, iterations=2000, seed=777, three_point=narrow)
    after = run_sra(schedule, iterations=2000, seed=777, three_point=wide)

    # The narrow p95 cannot exceed its own pessimistic bound (1500); the wide run
    # can reach far beyond it. The strict increase is the load-bearing assertion.
    assert before.p95 <= 1500
    assert after.p95 > before.p95
    # The sole task is always critical regardless of spread (sanity, not the point).
    assert before.criticality_index == {1: 1.0}
    assert after.criticality_index == {1: 1.0}


def test_lengthening_a_branch_increases_its_criticality() -> None:
    # Perturbation on the CRITICALITY output. Diamond: A -> {B, C} -> D(ms).
    # BEFORE: B=1440 (3d) dominates C=480 (1d) -> C is rarely on the path.
    # AFTER:  C=2400 (5d) dominates B -> C is on the path far more often.
    # Same seed; assert C's criticality strictly rises (and bound both in [0,1]).
    def diamond(c_minutes: int) -> Schedule:
        return _sched(
            [
                Task(unique_id=1, name="A", duration_minutes=960),
                Task(unique_id=2, name="B", duration_minutes=1440),
                Task(unique_id=3, name="C", duration_minutes=c_minutes),
                Task(unique_id=4, name="D", duration_minutes=0, is_milestone=True),
            ],
            [
                Relation(predecessor_id=1, successor_id=2),
                Relation(predecessor_id=1, successor_id=3),
                Relation(predecessor_id=2, successor_id=4),
                Relation(predecessor_id=3, successor_id=4),
            ],
        )

    before = run_sra(diamond(480), iterations=2000, seed=314, three_point=default_three_point)
    after = run_sra(diamond(2400), iterations=2000, seed=314, three_point=default_three_point)

    assert 0.0 <= before.criticality_index[3] <= 1.0
    assert 0.0 <= after.criticality_index[3] <= 1.0
    assert after.criticality_index[3] > before.criticality_index[3]


# --------------------------------------------------------------------------- #
# Error propagation + input guards: SRA never fabricates a result.
# --------------------------------------------------------------------------- #


def test_cyclic_base_schedule_propagates_cpm_error() -> None:
    # A <-> B logic cycle: the base CPM raises, so run_sra must raise BEFORE any
    # sampling -- never an averaged/fabricated number.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=2, successor_id=1),
        ],
    )
    with pytest.raises(CPMError):
        run_sra(schedule, iterations=10, seed=1)


def test_deferred_constraint_base_schedule_propagates_cpm_error() -> None:
    # A Must-Start-On constraint is deferred by the CPM engine, which RAISES.
    # That error must surface unchanged through run_sra.
    schedule = _sched(
        [
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                constraint_type=ConstraintType.MSO,
                constraint_date=_START,
            ),
        ]
    )
    with pytest.raises(CPMError):
        run_sra(schedule, iterations=10, seed=1)


def test_nonpositive_iterations_rejected() -> None:
    schedule = _sched([Task(unique_id=1, name="A", duration_minutes=480)])
    with pytest.raises(ValueError, match="iterations"):
        run_sra(schedule, iterations=0, seed=1)
    with pytest.raises(ValueError, match="iterations"):
        run_sra(schedule, iterations=-5, seed=1)
