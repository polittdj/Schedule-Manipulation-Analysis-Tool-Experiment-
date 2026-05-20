"""M2: strict / frozen / referential-integrity / byte-equal round-trip tests."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.models import RelationType, Schedule, Task
from tests.conftest import make_calendar, make_relation, make_schedule, make_task


def _rich_schedule() -> Schedule:
    cal = make_calendar(
        holidays=(date(2026, 12, 25), date(2026, 1, 1), date(2026, 7, 4)),  # unsorted
    )
    return make_schedule(
        calendars=(cal,),
        tasks=(make_task(1), make_task(2, duration_minutes=960), make_task(3, duration_minutes=0)),
        relations=(
            make_relation(1, 2),
            make_relation(2, 3, relation_type=RelationType.SS, lag_minutes=-120),
        ),
    )


def test_round_trip_is_byte_equal_and_value_equal() -> None:
    schedule = _rich_schedule()
    dumped = schedule.model_dump_json()
    restored = Schedule.model_validate_json(dumped)
    assert restored == schedule
    assert restored.model_dump_json() == dumped


def test_holidays_and_weekdays_are_normalized() -> None:
    cal = make_calendar(
        holidays=(date(2026, 12, 25), date(2026, 1, 1), date(2026, 1, 1)),  # unsorted + dup
        working_weekdays=(5, 1, 3, 1),  # unsorted + dup
    )
    assert cal.holidays == (date(2026, 1, 1), date(2026, 12, 25))
    assert cal.working_weekdays == (1, 3, 5)


def test_models_are_frozen(sample_schedule: Schedule) -> None:
    with pytest.raises(ValidationError):
        sample_schedule.name = "mutated"
    with pytest.raises(ValidationError):
        sample_schedule.tasks[0].unique_id = 999


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        Task(unique_id=1, name="x", duration_minutes=10, calendar_id=1, bogus=True)


def test_strict_rejects_implicit_coercion() -> None:
    with pytest.raises(ValidationError):
        Task(unique_id="1", name="x", duration_minutes=10, calendar_id=1)
    with pytest.raises(ValidationError):
        Task(unique_id=1, name="x", duration_minutes=10.0, calendar_id=1)


def test_duration_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        make_task(1, duration_minutes=-1)


def test_hours_per_day_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make_calendar(hours_per_day=0)


def test_unique_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        make_schedule(tasks=(make_task(1), make_task(1)), relations=())


def test_task_calendar_ref_must_exist() -> None:
    with pytest.raises(ValidationError):
        make_schedule(tasks=(make_task(1, calendar_id=99),), relations=())


def test_relation_endpoints_must_exist() -> None:
    with pytest.raises(ValidationError):
        make_schedule(tasks=(make_task(1), make_task(2)), relations=(make_relation(1, 3),))


def test_self_loop_relation_rejected() -> None:
    with pytest.raises(ValidationError):
        make_relation(1, 1)


def test_relation_type_serializes_as_value() -> None:
    relation = make_relation(1, 2, relation_type=RelationType.SF)
    assert json.loads(relation.model_dump_json())["relation_type"] == "SF"


def test_task_deadline_round_trips() -> None:
    task = make_task(1, deadline=datetime(2026, 3, 1, 17, 0))
    restored = Task.model_validate_json(task.model_dump_json())
    assert restored == task
    assert restored.deadline == datetime(2026, 3, 1, 17, 0)
    assert make_task(2).deadline is None  # defaults to no deadline
