"""CPM engine tests against independently hand-computed expected values.

Every numeric expectation here is hand-derived (see the comments), never read
back from the engine's own output -- that is what makes the suite a fidelity
proof rather than a tautology (LAW 2 / H-VACUOUS-TEST). The calendar is the
default 480 working minutes/day, so 1 day == 480 minutes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pytest

from schedule_forensics.cpm import CPMError, compute_cpm, offset_to_datetime
from schedule_forensics.schemas import Calendar, Relation, Schedule, Task

_START = dt.datetime(2025, 1, 6, 8)  # a Monday


def _sched(tasks: Iterable[Task], relations: Iterable[Relation] = ()) -> Schedule:
    return Schedule(name="t", project_start=_START, tasks=tuple(tasks), relations=tuple(relations))


def test_linear_chain_all_critical() -> None:
    # A(2d) -> B(3d) -> C(1d): finishes at 960+1440+480 = 2880; whole chain critical.
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
    result = compute_cpm(schedule)
    assert (result.timings[1].early_start, result.timings[1].early_finish) == (0, 960)
    assert (result.timings[2].early_start, result.timings[2].early_finish) == (960, 2400)
    assert (result.timings[3].early_start, result.timings[3].early_finish) == (2400, 2880)
    assert result.project_finish == 2880
    assert all(timing.total_float == 0 for timing in result.timings.values())
    assert result.critical_path == (1, 2, 3)


def test_parallel_branch_has_float() -> None:
    # A(2d) -> {B(3d), C(1d)} -> D(milestone). C carries 960 min (2 day) slack.
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
    result = compute_cpm(schedule)
    assert result.project_finish == 2400
    assert result.timings[3].total_float == 960
    assert result.timings[3].free_float == 960
    assert result.timings[3].is_critical is False
    assert result.timings[1].total_float == 0
    assert result.timings[2].total_float == 0
    assert result.critical_path == (1, 2, 4)


def test_lag_pushes_successor() -> None:
    # A(1d) -> B(1d) with a +1 day (480 min) lag: B starts at 480 + 480 = 960.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ],
        [Relation(predecessor_id=1, successor_id=2, lag_minutes=480)],
    )
    result = compute_cpm(schedule)
    assert result.timings[2].early_start == 960
    assert result.timings[2].early_finish == 1440
    assert result.project_finish == 1440


def test_required_finish_makes_float_negative() -> None:
    # A(2d) -> B(2d): network finish 1920; require finish at 1440 -> -480 on the chain.
    schedule = _sched(
        [
            Task(unique_id=1, name="A", duration_minutes=960),
            Task(unique_id=2, name="B", duration_minutes=960),
        ],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    result = compute_cpm(schedule, required_finish_offset=1440)
    assert result.project_finish == 1920  # the network's own early finish is unchanged
    assert result.timings[2].total_float == -480
    assert result.timings[1].total_float == -480
    assert result.timings[2].is_critical is True


def test_perturbation_flips_criticality() -> None:
    # Mutation discipline: lengthening the slack branch must change the verdict.
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
    baseline = compute_cpm(_sched(base, rels))
    assert baseline.timings[3].is_critical is False

    perturbed_tasks = [
        task if task.unique_id != 3 else Task(unique_id=3, name="C", duration_minutes=1440)
        for task in base
    ]
    perturbed = compute_cpm(_sched(perturbed_tasks, rels))
    assert perturbed.timings[3].is_critical is True
    assert perturbed.timings[3].total_float == 0


def test_cycle_raises() -> None:
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
        compute_cpm(schedule)


def test_summary_tasks_excluded_from_network() -> None:
    # A summary task is a rollup, not an activity; it must not appear in timings.
    schedule = _sched(
        [
            Task(unique_id=1, name="Phase", duration_minutes=999, is_summary=True),
            Task(unique_id=2, name="A", duration_minutes=480),
        ]
    )
    result = compute_cpm(schedule)
    assert 1 not in result.timings
    assert result.project_finish == 480


def test_offset_to_datetime_spans_weekend() -> None:
    calendar = Calendar()
    friday = dt.datetime(2025, 1, 10, 8)
    assert offset_to_datetime(friday, 0, calendar) == friday
    assert offset_to_datetime(friday, 480, calendar) == dt.datetime(2025, 1, 10, 16)
    # 2 working days from Friday skips the weekend -> Monday 16:00
    assert offset_to_datetime(friday, 960, calendar) == dt.datetime(2025, 1, 13, 16)


def test_offset_to_datetime_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        offset_to_datetime(_START, -1, Calendar())
