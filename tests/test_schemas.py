"""Schema contract tests: identity, referential integrity, immutability, round-trip.

Several of these are perturbation tests (H-VACUOUS-TEST): they assert that an
*invalid* construction FAILS, proving the validator actually fires.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from schedule_forensics.schemas import (
    ConstraintType,
    Relation,
    RelationType,
    Schedule,
    Task,
)

_START = dt.datetime(2025, 1, 6, 8)


def _task(uid: int, name: str = "T", minutes: int = 480, **kwargs: object) -> Task:
    return Task(unique_id=uid, name=name, duration_minutes=minutes, **kwargs)  # type: ignore[arg-type]


def test_valid_schedule_constructs() -> None:
    schedule = Schedule(
        name="P",
        project_start=_START,
        tasks=(_task(1), _task(2)),
        relations=(Relation(predecessor_id=1, successor_id=2),),
    )
    assert schedule.task_by_id(2).unique_id == 2
    assert schedule.calendar.working_minutes_per_day == 480
    assert schedule.relations[0].type is RelationType.FS


def test_duplicate_unique_id_rejected() -> None:
    with pytest.raises(ValidationError):
        Schedule(name="P", project_start=_START, tasks=(_task(1), _task(1)))


def test_relation_to_missing_task_rejected() -> None:
    with pytest.raises(ValidationError):
        Schedule(
            name="P",
            project_start=_START,
            tasks=(_task(1),),
            relations=(Relation(predecessor_id=1, successor_id=99),),
        )


def test_self_relation_rejected() -> None:
    with pytest.raises(ValidationError):
        Schedule(
            name="P",
            project_start=_START,
            tasks=(_task(1),),
            relations=(Relation(predecessor_id=1, successor_id=1),),
        )


def test_frozen_is_immutable() -> None:
    task = _task(1)
    with pytest.raises(ValidationError):
        task.name = "changed"  # type: ignore[misc]


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        Task(unique_id=1, name="T", duration_minutes=1, bogus=1)  # type: ignore[call-arg]


def test_negative_duration_rejected() -> None:
    with pytest.raises(ValidationError):
        _task(1, minutes=-1)


def test_json_round_trip_is_lossless() -> None:
    schedule = Schedule(
        name="P",
        project_start=_START,
        status_date=dt.datetime(2025, 1, 20, 17),
        tasks=(_task(1, minutes=960), _task(2, minutes=480, constraint_type=ConstraintType.SNET)),
        relations=(Relation(predecessor_id=1, successor_id=2, lag_minutes=120),),
    )
    assert Schedule.model_validate_json(schedule.model_dump_json()) == schedule
