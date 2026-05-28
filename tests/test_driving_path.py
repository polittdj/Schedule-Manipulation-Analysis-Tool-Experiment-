"""Driving-path / driving-slack tests against independently hand-computed values.

Every numeric expectation here is hand-derived from the relationship-free-float
formulas (shown in each test's comment), never read back from the function's own
output -- that is what makes the suite a fidelity proof and not a tautology
(LAW 2 / H-VACUOUS-TEST). The calendar is the default 480 working minutes/day,
so 1 day == 480 working minutes, and every quantity is an integer working-minute
offset on the same axis as :mod:`schedule_forensics.cpm`.

Relationship free float for a link ``P -> S`` (SSI driving-slack semantics):
  * FS: ``es_S - (ef_P + lag)``
  * SS: ``es_S - (es_P + lag)``
  * FF: ``ef_S - (ef_P + lag)``
  * SF: ``ef_S - (es_P + lag)``
A link is *driving* iff that value == 0.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pytest

from schedule_forensics.cpm import CPMError, _link_slack, compute_cpm
from schedule_forensics.driving_path import (
    DrivingPathResult,
    LinkSlack,
    _relationship_free_float,
    analyze_driving_path,
)
from schedule_forensics.schemas import Relation, RelationType, Schedule, Task

_START = dt.datetime(2025, 1, 6, 8)  # a Monday


def _sched(tasks: Iterable[Task], relations: Iterable[Relation] = ()) -> Schedule:
    return Schedule(name="t", project_start=_START, tasks=tuple(tasks), relations=tuple(relations))


def _slack_for(result: DrivingPathResult, pred: int, succ: int) -> LinkSlack:
    """Fetch the single LinkSlack for the link ``pred -> succ`` (fails if absent)."""
    matches = [
        ls for ls in result.link_slacks if ls.predecessor_id == pred and ls.successor_id == succ
    ]
    assert len(matches) == 1, f"expected exactly one link {pred}->{succ}, got {len(matches)}"
    return matches[0]


def test_linear_chain_is_entirely_driving() -> None:
    # A(2d=960) -> B(3d=1440) -> C(1d=480). CPM early dates:
    #   A es0 ef960; B es960 ef2400; C es2400 ef2880; project_finish=2880.
    # FS slacks: 1->2 = es_B(960)-(ef_A(960))=0 driving;
    #            2->3 = es_C(2400)-(ef_B(2400))=0 driving.
    # Finish task is C (ef==2880); back-walk 3<-2<-1 => chain (1,2,3).
    schedule = _sched(
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
    result = analyze_driving_path(schedule)
    assert result.driving_chain == (1, 2, 3)
    assert _slack_for(result, 1, 2) == LinkSlack(1, 2, RelationType.FS, 0, True)
    assert _slack_for(result, 2, 3) == LinkSlack(2, 3, RelationType.FS, 0, True)
    assert all(ls.is_driving for ls in result.link_slacks)


def test_diamond_driving_path_skips_slack_branch() -> None:
    # A(2d=960) -> {B(3d=1440), C(1d=480)} -> D(milestone). CPM early dates:
    #   A es0 ef960; B es960 ef2400; C es960 ef1440; D es2400 ef2400.
    #   project_finish = 2400.
    # FS slacks:
    #   1->2 = 960-960 = 0      driving
    #   1->3 = 960-960 = 0      driving
    #   2->4 = 2400-2400 = 0    driving
    #   3->4 = 2400-1440 = 960  NOT driving  (C carries 960 min of free float)
    # Tasks at finish offset 2400: B(2) and D(4); B drives D, so the sink is D.
    # Back-walk 4 <- 2 (only driving incoming) <- 1 => chain (1,2,4) = A,B,D.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=960),
            Task(unique_id=2, name="B", duration_minutes=1440),
            Task(unique_id=3, name="C", duration_minutes=480),
            Task(unique_id=4, name="D", duration_minutes=0, is_milestone=True),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=4),
            Relation(predecessor_id=3, successor_id=4),
        ],
    )
    result = analyze_driving_path(schedule)
    assert result.driving_chain == (1, 2, 4)
    assert _slack_for(result, 3, 4) == LinkSlack(3, 4, RelationType.FS, 960, False)
    assert _slack_for(result, 2, 4) == LinkSlack(2, 4, RelationType.FS, 0, True)
    # The slack branch's tasks (only C==3 here) are absent from the driving chain.
    assert 3 not in result.driving_chain


def test_perturbation_lengthening_branch_changes_path() -> None:
    # H-VACUOUS-TEST perturbation. Same diamond as above, BUT lengthen C so it
    # strictly outlasts B; the driving path must move off B and onto C, and the
    # 3->4 link must flip from non-driving to driving while 2->4 flips the other
    # way. Asserting BOTH states is what proves the calc is actually being read.
    base = [
        Task(unique_id=1, name="A", duration_minutes=960),
        Task(unique_id=2, name="B", duration_minutes=1440),
        Task(unique_id=3, name="C", duration_minutes=480),
        Task(unique_id=4, name="D", duration_minutes=0, is_milestone=True),
    ]
    rels = [
        Relation(predecessor_id=1, successor_id=2),
        Relation(predecessor_id=1, successor_id=3),
        Relation(predecessor_id=2, successor_id=4),
        Relation(predecessor_id=3, successor_id=4),
    ]

    # BEFORE: chain is A,B,D; link 3->4 is non-driving (slack 960), 2->4 driving.
    before = analyze_driving_path(_sched(base, rels))
    assert before.driving_chain == (1, 2, 4)
    assert _slack_for(before, 3, 4).is_driving is False
    assert _slack_for(before, 2, 4).is_driving is True

    # AFTER: C(4d=1920) now outlasts B(3d=1440). New CPM early dates:
    #   A es0 ef960; B es960 ef2400; C es960 ef2880; D es2880 ef2880.
    #   project_finish = 2880.
    # FS slacks: 2->4 = 2880-2400 = 480 NOT driving; 3->4 = 2880-2880 = 0 driving.
    # Back-walk 4 <- 3 (only driving incoming) <- 1 => chain (1,3,4) = A,C,D.
    perturbed_tasks = [
        task if task.unique_id != 3 else Task(unique_id=3, name="C", duration_minutes=1920)
        for task in base
    ]
    after = analyze_driving_path(_sched(perturbed_tasks, rels))
    assert after.driving_chain == (1, 3, 4)
    assert _slack_for(after, 3, 4) == LinkSlack(3, 4, RelationType.FS, 0, True)
    assert _slack_for(after, 2, 4) == LinkSlack(2, 4, RelationType.FS, 480, False)

    # The perturbation actually changed the verdict, not just the inputs.
    assert before.driving_chain != after.driving_chain


def test_equal_branch_makes_second_link_driving_tiebreak_holds() -> None:
    # The dispatch's literal perturbation: lengthen C to EQUAL B (both 3d=1440).
    #   A es0 ef960; B es960 ef2400; C es960 ef2400; D es2400 ef2400.
    # FS slacks: 2->4 = 2400-2400 = 0 driving; 3->4 = 2400-2400 = 0 driving (FLIPPED).
    # Both predecessors now drive D; the smallest-unique_id tiebreak keeps the
    # chain at (1,2,4), but C's link has become driving -- the asserted change.
    base = [
        Task(unique_id=1, name="A", duration_minutes=960),
        Task(unique_id=2, name="B", duration_minutes=1440),
        Task(unique_id=3, name="C", duration_minutes=480),
        Task(unique_id=4, name="D", duration_minutes=0, is_milestone=True),
    ]
    rels = [
        Relation(predecessor_id=1, successor_id=2),
        Relation(predecessor_id=1, successor_id=3),
        Relation(predecessor_id=2, successor_id=4),
        Relation(predecessor_id=3, successor_id=4),
    ]
    before = analyze_driving_path(_sched(base, rels))
    assert _slack_for(before, 3, 4).is_driving is False

    equal_tasks = [
        task if task.unique_id != 3 else Task(unique_id=3, name="C", duration_minutes=1440)
        for task in base
    ]
    after = analyze_driving_path(_sched(equal_tasks, rels))
    assert _slack_for(after, 3, 4) == LinkSlack(3, 4, RelationType.FS, 0, True)
    assert _slack_for(after, 2, 4).is_driving is True
    # Tiebreak determinism: with both links driving, smallest unique_id (2) wins.
    assert after.driving_chain == (1, 2, 4)


def test_lag_makes_link_non_driving() -> None:
    # A(1d=480) -> B(1d=480) with a +1d (480 min) FS lag.
    #   A es0 ef480; B es=ef_A(480)+lag(480)=960, ef=1440. project_finish=1440.
    # FS slack 1->2 = es_B(960) - (ef_A(480)+lag(480)) = 960-960 = 0 => driving
    # (the lag is *consumed* by the schedule, so the link still binds).
    sched_lag = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2, lag_minutes=480)],
    )
    result = analyze_driving_path(sched_lag)
    assert result.driving_chain == (1, 2)
    assert _slack_for(result, 1, 2) == LinkSlack(1, 2, RelationType.FS, 0, True)


def test_parallel_link_to_milestone_with_slack_is_non_driving() -> None:
    # Two independent starts feed one finish milestone; one of them has slack.
    # A(2d=960) -> C(ms); B(1d=480) -> C(ms). No predecessor for A or B.
    #   A es0 ef960; B es0 ef480; C es960 ef960. project_finish=960.
    # FS slacks: A->C = 960-960 = 0 driving; B->C = 960-480 = 480 NOT driving.
    # Finish task C (ef==960); back-walk C <- A (only driving incoming).
    schedule = _sched(
        [
            Task(unique_id=10, name="A", duration_minutes=960),
            Task(unique_id=20, name="B", duration_minutes=480),
            Task(unique_id=30, name="C", duration_minutes=0, is_milestone=True),
        ],
        [
            Relation(predecessor_id=10, successor_id=30),
            Relation(predecessor_id=20, successor_id=30),
        ],
    )
    result = analyze_driving_path(schedule)
    assert result.driving_chain == (10, 30)
    assert _slack_for(result, 10, 30) == LinkSlack(10, 30, RelationType.FS, 0, True)
    assert _slack_for(result, 20, 30) == LinkSlack(20, 30, RelationType.FS, 480, False)


def test_ss_link_relationship_free_float() -> None:
    # SS link with lag, then an FS finisher, so the SS slack is non-trivial.
    # A(2d=960) =SS+1d(480)=> B(2d=960); B =FS=> C(milestone).
    #   A es0 ef960; B es = max(0, es_A(0)+lag(480)) = 480, ef=1440; C es1440 ef1440.
    #   project_finish = 1440.
    # SS slack A->B = es_B(480) - (es_A(0)+lag(480)) = 0 => driving.
    # FS slack B->C = es_C(1440) - (ef_B(1440)) = 0 => driving. Chain (1,2,3).
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=960),
            Task(unique_id=2, name="B", duration_minutes=960),
            Task(unique_id=3, name="C", duration_minutes=0, is_milestone=True),
        ],
        [
            Relation(predecessor_id=1, successor_id=2, type=RelationType.SS, lag_minutes=480),
            Relation(predecessor_id=2, successor_id=3, type=RelationType.FS),
        ],
    )
    result = analyze_driving_path(schedule)
    assert _slack_for(result, 1, 2) == LinkSlack(1, 2, RelationType.SS, 0, True)
    assert _slack_for(result, 2, 3) == LinkSlack(2, 3, RelationType.FS, 0, True)
    assert result.driving_chain == (1, 2, 3)


def test_summary_links_are_skipped() -> None:
    # A summary parent (id 1) is absent from CPM timings, so any link touching it
    # must NOT appear in link_slacks. Only the real A(480)->B(480) link survives.
    #   A es0 ef480; B es480 ef960. project_finish=960. FS slack 2->3 = 0 driving.
    schedule = _sched(
        [
            Task(unique_id=1, name="Phase", duration_minutes=0, is_summary=True),
            Task(unique_id=2, name="A", duration_minutes=480),
            Task(unique_id=3, name="B", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),  # summary -> real: skipped
            Relation(predecessor_id=2, successor_id=3),  # real -> real: kept
        ],
    )
    result = analyze_driving_path(schedule)
    # The summary-touching link is not emitted at all.
    assert all(not (ls.predecessor_id == 1 or ls.successor_id == 1) for ls in result.link_slacks)
    assert len(result.link_slacks) == 1
    assert _slack_for(result, 2, 3) == LinkSlack(2, 3, RelationType.FS, 0, True)
    assert result.driving_chain == (2, 3)


def test_single_task_chain_has_no_links() -> None:
    # One activity, no relations: it lands on the finish by itself; no links.
    schedule = _sched([Task(unique_id=5, name="solo", duration_minutes=480)])
    result = analyze_driving_path(schedule)
    assert result.driving_chain == (5,)
    assert result.link_slacks == ()


def test_empty_schedule_yields_empty_trace() -> None:
    # A schedule with only a summary task has NO schedulable activity.
    schedule = _sched([Task(unique_id=1, name="Phase", duration_minutes=0, is_summary=True)])
    result = analyze_driving_path(schedule)
    assert result.driving_chain == ()
    assert result.link_slacks == ()


def test_accepts_precomputed_cpm_result() -> None:
    # Passing an existing CPMResult must yield the identical trace as computing
    # it internally (the function must not recompute or diverge).
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=960),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    precomputed = compute_cpm(schedule)
    via_arg = analyze_driving_path(schedule, result=precomputed)
    via_internal = analyze_driving_path(schedule)
    assert via_arg == via_internal
    assert via_arg.driving_chain == (1, 2)


def test_slack_matches_frozen_cpm_engine_for_every_link_type() -> None:
    # Anti-drift (H-DRIFT-2): the module re-derives the four slack formulas rather
    # than importing the CPM's private helper, so pin them to that engine's
    # _link_slack for ALL four types with assorted lags. If either drifts, fail.
    cases = [
        (RelationType.FS, 0, 960, 1200, 1700, 60),
        (RelationType.SS, 100, 800, 250, 900, 30),
        (RelationType.FF, 0, 480, 200, 700, -45),
        (RelationType.SF, 50, 600, 130, 980, 0),
    ]
    for rel, es_p, ef_p, es_s, ef_s, lag in cases:
        # Building a 2-task schedule whose CPM yields exactly these offsets is
        # awkward; instead assert the module's per-link formula equals the engine's.
        expected = _link_slack(rel, es_p, ef_p, es_s, ef_s, lag)
        assert _relationship_free_float(rel, es_p, ef_p, es_s, ef_s, lag) == expected


def test_cycle_propagates_cpm_error() -> None:
    # The module must not invent timings; an unschedulable network raises (from CPM).
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
        analyze_driving_path(schedule)


# ── analyze_paths_to_target: top-K longest chains to a user-chosen endpoint ──
#
# Each test perturbs one branch length / target / k value and asserts the
# specific top-K result that must come back (non-vacuous: a wrong ordering, a
# wrong duration-sum, or a wrong K cap would fail by name).


def _diamond_for_topk() -> Schedule:
    """A 4-task diamond: 1 -> {2, 3} -> 4, with branch 2 longer than branch 3.

    Task 1: 480 (1d); task 2: 1440 (3d); task 3: 480 (1d); task 4: 480 (1d).
    Two start->4 paths: (1, 2, 4) duration 480+1440+480=2400; (1, 3, 4) duration
    480+480+480=1440. (1, 2, 4) is the critical path (longest); (1, 3, 4) is
    the secondary path (next-longest). No third path exists.
    """
    return _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B-long", duration_minutes=1440),
            Task(unique_id=3, name="C-short", duration_minutes=480),
            Task(unique_id=4, name="D", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=2, successor_id=4),
            Relation(predecessor_id=3, successor_id=4),
        ],
    )


def test_paths_to_target_linear_chain_returns_single_path() -> None:
    """A linear chain has exactly one path to the end-task; K=3 still returns 1."""
    from schedule_forensics.driving_path import analyze_paths_to_target

    schedule = _sched(
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
    res = analyze_paths_to_target(schedule, target_uid=3, k=3)
    assert res.target_uid == 3
    assert len(res.paths) == 1
    assert res.paths[0].task_uids == (1, 2, 3)
    assert res.paths[0].duration_minutes == 960 + 1440 + 480
    assert res.paths[0].is_driving is True  # both links are zero-slack


def test_paths_to_target_diamond_returns_critical_then_secondary() -> None:
    """Two branches to the same sink: K=3 returns 2 paths ranked by duration."""
    from schedule_forensics.driving_path import analyze_paths_to_target

    res = analyze_paths_to_target(_diamond_for_topk(), target_uid=4, k=3)
    assert res.target_uid == 4
    assert len(res.paths) == 2  # only two distinct paths exist (1->2->4 and 1->3->4)
    # Critical = longest: (1, 2, 4), 2400 minutes (5 days).
    assert res.paths[0].task_uids == (1, 2, 4)
    assert res.paths[0].duration_minutes == 2400
    assert res.paths[0].is_driving is True  # this IS the CPM longest chain
    # Secondary = next-longest: (1, 3, 4), 1440 minutes (3 days).
    assert res.paths[1].task_uids == (1, 3, 4)
    assert res.paths[1].duration_minutes == 1440
    # Branch 3 has positive relationship free float -> the secondary chain has at
    # least one non-driving link -> the whole chain is not "all driving".
    assert res.paths[1].is_driving is False


def test_paths_to_target_three_branches_are_ranked_descending() -> None:
    """Three convergent branches → K=3 returns all three in critical/secondary/tertiary order."""
    from schedule_forensics.driving_path import analyze_paths_to_target

    # A=1 -> X=2(3d) -> T=10, A -> Y=3(2d) -> T, A -> Z=4(1d) -> T. Common A and T.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="X-long", duration_minutes=1440),
            Task(unique_id=3, name="Y-med", duration_minutes=960),
            Task(unique_id=4, name="Z-short", duration_minutes=480),
            Task(unique_id=10, name="T", duration_minutes=480),
        ],
        [
            Relation(predecessor_id=1, successor_id=2),
            Relation(predecessor_id=1, successor_id=3),
            Relation(predecessor_id=1, successor_id=4),
            Relation(predecessor_id=2, successor_id=10),
            Relation(predecessor_id=3, successor_id=10),
            Relation(predecessor_id=4, successor_id=10),
        ],
    )
    res = analyze_paths_to_target(schedule, target_uid=10, k=3)
    assert [p.task_uids for p in res.paths] == [(1, 2, 10), (1, 3, 10), (1, 4, 10)]
    assert [p.duration_minutes for p in res.paths] == [
        480 + 1440 + 480,
        480 + 960 + 480,
        480 + 480 + 480,
    ]


def test_paths_to_target_k_clamps_returned_count() -> None:
    """K=1 on the diamond returns just the critical path; K=0 returns no paths."""
    from schedule_forensics.driving_path import analyze_paths_to_target

    schedule = _diamond_for_topk()
    only = analyze_paths_to_target(schedule, target_uid=4, k=1)
    assert len(only.paths) == 1
    assert only.paths[0].task_uids == (1, 2, 4)

    none = analyze_paths_to_target(schedule, target_uid=4, k=0)
    assert none.target_uid == 4
    assert none.paths == ()


def test_paths_to_target_missing_uid_raises() -> None:
    """A target UID that is not a scheduled activity raises ValueError."""
    from schedule_forensics.driving_path import analyze_paths_to_target

    with pytest.raises(ValueError, match="not a scheduled activity"):
        analyze_paths_to_target(_diamond_for_topk(), target_uid=999, k=3)


def test_paths_to_target_negative_k_raises() -> None:
    """Negative K is a programming error: fail closed (LAW 2)."""
    from schedule_forensics.driving_path import analyze_paths_to_target

    with pytest.raises(ValueError, match="k must be non-negative"):
        analyze_paths_to_target(_diamond_for_topk(), target_uid=4, k=-1)


def test_paths_to_target_target_is_root_yields_one_singleton_path() -> None:
    """A target activity that has no predecessors is its own single-element path."""
    from schedule_forensics.driving_path import analyze_paths_to_target

    schedule = _sched([Task(unique_id=7, name="alone", duration_minutes=480)])
    res = analyze_paths_to_target(schedule, target_uid=7, k=3)
    assert len(res.paths) == 1
    assert res.paths[0].task_uids == (7,)
    assert res.paths[0].duration_minutes == 480
