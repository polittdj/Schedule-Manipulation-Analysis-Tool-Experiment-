"""Shared test fixtures and a synthetic-Schedule factory.

The factory also serves as the stand-in the M3 parser seam is monkeypatched to return.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime

import pytest

from app.models import Calendar, Relation, RelationType, Schedule, Task

# Monday 2026-01-05, 08:00 — a working day aligned with the default day start.
DEFAULT_PROJECT_START = datetime(2026, 1, 5, 8, 0, 0)


def make_calendar(
    calendar_id: int = 1,
    *,
    name: str = "Standard 5-day",
    hours_per_day: int = 8,
    working_weekdays: Sequence[int] = (1, 2, 3, 4, 5),
    holidays: Iterable[date] = (),
) -> Calendar:
    return Calendar(
        calendar_id=calendar_id,
        name=name,
        hours_per_day=hours_per_day,
        working_weekdays=tuple(working_weekdays),
        holidays=tuple(holidays),
    )


def make_task(
    unique_id: int,
    *,
    name: str | None = None,
    duration_minutes: int = 480,
    calendar_id: int = 1,
    deadline: datetime | None = None,
) -> Task:
    return Task(
        unique_id=unique_id,
        name=name if name is not None else f"Task {unique_id}",
        duration_minutes=duration_minutes,
        calendar_id=calendar_id,
        deadline=deadline,
    )


def make_relation(
    predecessor_id: int,
    successor_id: int,
    *,
    relation_type: RelationType = RelationType.FS,
    lag_minutes: int = 0,
) -> Relation:
    return Relation(
        predecessor_id=predecessor_id,
        successor_id=successor_id,
        relation_type=relation_type,
        lag_minutes=lag_minutes,
    )


def make_schedule(
    *,
    name: str = "Sample schedule",
    project_start: datetime = DEFAULT_PROJECT_START,
    calendars: Sequence[Calendar] | None = None,
    tasks: Sequence[Task] | None = None,
    relations: Sequence[Relation] | None = None,
) -> Schedule:
    return Schedule(
        name=name,
        project_start=project_start,
        calendars=tuple(calendars) if calendars is not None else (make_calendar(),),
        tasks=tuple(tasks) if tasks is not None else (make_task(1), make_task(2)),
        relations=tuple(relations) if relations is not None else (make_relation(1, 2),),
    )


@pytest.fixture
def sample_schedule() -> Schedule:
    return make_schedule()
