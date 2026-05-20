"""The core schedule data model: Task, Relation, Schedule."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.calendar import Calendar
from app.models.enums import RelationType


class Task(BaseModel):
    """A schedule activity.

    Identity is ``unique_id`` only — never ``name`` or any external id. This is the sole
    valid key for cross-version matching downstream.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    unique_id: int
    name: str
    duration_minutes: int = Field(ge=0)  # working-time minutes; a milestone has 0
    calendar_id: int


class Relation(BaseModel):
    """A precedence tie between two tasks, addressed by UniqueID.

    ``lag_minutes`` is signed working-time: negative is a lead, positive is a lag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    predecessor_id: int
    successor_id: int
    relation_type: RelationType
    lag_minutes: int

    @model_validator(mode="after")
    def _reject_self_loop(self) -> Self:
        if self.predecessor_id == self.successor_id:
            raise ValueError(f"a relation cannot tie task {self.predecessor_id} to itself")
        return self


class Schedule(BaseModel):
    """A complete schedule: its calendars, tasks, and logic relations.

    A ``model_validator`` enforces referential integrity, so an invalid schedule is
    unconstructable — a guarantee the CPM engine and metrics rely on.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: str
    project_start: datetime
    calendars: tuple[Calendar, ...]
    tasks: tuple[Task, ...]
    relations: tuple[Relation, ...]

    @model_validator(mode="after")
    def _check_integrity(self) -> Self:
        calendar_ids = [c.calendar_id for c in self.calendars]
        if len(calendar_ids) != len(set(calendar_ids)):
            raise ValueError("calendar_id values must be unique within a schedule")
        known_calendars = set(calendar_ids)

        task_ids = [t.unique_id for t in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task unique_id values must be unique within a schedule")
        known_tasks = set(task_ids)

        for task in self.tasks:
            if task.calendar_id not in known_calendars:
                raise ValueError(
                    f"task {task.unique_id} references unknown calendar_id {task.calendar_id}"
                )

        for relation in self.relations:
            if relation.predecessor_id not in known_tasks:
                raise ValueError(
                    f"relation predecessor {relation.predecessor_id} is not a task in this schedule"
                )
            if relation.successor_id not in known_tasks:
                raise ValueError(
                    f"relation successor {relation.successor_id} is not a task in this schedule"
                )
        return self
