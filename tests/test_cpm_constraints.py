"""CPM date-constraint + deadline tests (honored under 'honor constraint dates').

Constraint datetimes use 08:00 (the project-start clock), so the intraday term is
0 and every offset is a clean whole number of working days * 480. Expected float
values are hand-computed; the violation cases assert NEGATIVE float (a forensic
red flag), and a perturbation flips the verdict (H-VACUOUS-TEST).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pytest

from schedule_forensics.cpm import CPMError, compute_cpm, datetime_to_offset
from schedule_forensics.schemas import Calendar, ConstraintType, Relation, Schedule, Task

_START = dt.datetime(2025, 1, 6, 8)  # Monday 08:00


def _task(uid: int, dur: int, **kwargs: object) -> Task:
    return Task(unique_id=uid, name=f"T{uid}", duration_minutes=dur, **kwargs)  # type: ignore[arg-type]


def _sched(tasks: Iterable[Task], relations: Iterable[Relation] = ()) -> Schedule:
    return Schedule(name="t", project_start=_START, tasks=tuple(tasks), relations=tuple(relations))


def test_offset_zero_at_start() -> None:
    assert datetime_to_offset(_START, _START, Calendar()) == 0


def test_offset_counts_working_days() -> None:
    # Mon 08:00 -> Wed 08:00 spans Mon + Tue = 2 working days = 960.
    assert datetime_to_offset(_START, dt.datetime(2025, 1, 8, 8), Calendar()) == 960


def test_offset_skips_weekend() -> None:
    # Mon 01-06 -> Mon 01-13 = 5 working days (weekend skipped) = 2400.
    assert datetime_to_offset(_START, dt.datetime(2025, 1, 13, 8), Calendar()) == 2400


def test_offset_intraday_clamped() -> None:
    assert datetime_to_offset(_START, dt.datetime(2025, 1, 6, 12), Calendar()) == 240
    # Beyond one working day clamps to working_minutes_per_day.
    assert datetime_to_offset(_START, dt.datetime(2025, 1, 6, 20), Calendar()) == 480


def test_snet_floors_early_start() -> None:
    schedule = _sched(
        [
            _task(
                1,
                480,
                constraint_type=ConstraintType.SNET,
                constraint_date=dt.datetime(2025, 1, 8, 8),
            )
        ]
    )
    result = compute_cpm(schedule)
    assert result.timings[1].early_start == 960  # floored to the SNET offset
    assert result.timings[1].early_finish == 1440


def test_fnet_floors_early_finish() -> None:
    schedule = _sched(
        [
            _task(
                1,
                480,
                constraint_type=ConstraintType.FNET,
                constraint_date=dt.datetime(2025, 1, 8, 8),
            )
        ]
    )
    result = compute_cpm(schedule)
    assert result.timings[1].early_finish == 960  # EF floored to the FNET offset
    assert result.timings[1].early_start == 480


def test_fnlt_violation_makes_float_negative() -> None:
    # A(2d=960) FNLT Tue 08:00 (480): LF capped below EF -> total float -480.
    schedule = _sched(
        [
            _task(
                1,
                960,
                constraint_type=ConstraintType.FNLT,
                constraint_date=dt.datetime(2025, 1, 7, 8),
            )
        ]
    )
    result = compute_cpm(schedule)
    assert result.timings[1].total_float == -480
    assert result.timings[1].is_critical is True


def test_snlt_violation_propagates_negative_float() -> None:
    # Pre(2d) -> A(1d); A SNLT Mon 08:00 (offset 0) but logic forces A.ES=960.
    # LF cap = 0 + 480 = 480 -> A total float -960, propagated back to Pre.
    schedule = _sched(
        [
            _task(10, 960),
            _task(1, 480, constraint_type=ConstraintType.SNLT, constraint_date=_START),
        ],
        [Relation(predecessor_id=10, successor_id=1)],
    )
    result = compute_cpm(schedule)
    assert result.timings[1].total_float == -960
    assert result.timings[10].total_float == -960


def test_deadline_drives_negative_float_and_propagates() -> None:
    # A(1d) -> B(1d); B deadline Tue 08:00 (480) < B.EF (960) -> B and A go negative.
    schedule = _sched(
        [_task(1, 480), _task(2, 480, deadline=dt.datetime(2025, 1, 7, 8))],
        [Relation(predecessor_id=1, successor_id=2)],
    )
    result = compute_cpm(schedule)
    assert result.timings[2].total_float == -480
    assert result.timings[1].total_float == -480


def test_deadline_perturbation_flips_float() -> None:
    # Mutation: adding a tight deadline turns a float-0 task negative.
    assert compute_cpm(_sched([_task(1, 480)])).timings[1].total_float == 0
    tight = _sched([_task(1, 480, deadline=_START)])  # deadline at offset 0
    assert compute_cpm(tight).timings[1].total_float == -480


def test_mfo_raises() -> None:
    schedule = _sched(
        [
            _task(
                1,
                480,
                constraint_type=ConstraintType.MFO,
                constraint_date=dt.datetime(2025, 1, 8, 8),
            )
        ]
    )
    with pytest.raises(CPMError, match="not yet honored"):
        compute_cpm(schedule)


def test_date_constraint_without_date_raises() -> None:
    schedule = _sched([_task(1, 480, constraint_type=ConstraintType.SNET)])
    with pytest.raises(CPMError, match="constraint_date"):
        compute_cpm(schedule)
