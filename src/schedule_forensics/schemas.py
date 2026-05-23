"""Frozen, strict data model for Schedule Forensics (the trust-root contract).

Every downstream module consumes these types unchanged. Cross-version task
identity is by ``Task.unique_id`` ONLY -- never the row ``ID`` (which renumbers
on insert/delete) and never the name (not unique). See CLAUDE.md, commandment 3.

Models are ``frozen`` (immutable, hashable), ``strict`` (no silent type
coercion), and ``extra="forbid"`` (an unknown field is an error, not a silent
drop) so that an invalid schedule is *unconstructable*.

Freeze status: FROZEN at SCHEMA_VERSION below. CHANGE CONTROL: any field
add/remove/rename requires bumping ``SCHEMA_VERSION`` and updating
``tests/test_schema_freeze.py`` in the same change (the field-set guard test
fails otherwise) -- this is deliberate. Change log:

  * v1.0.0 -- trust-root spine (before the Phase-5 analysis fan-out).
  * v1.1.0 -- added earned-value fields ``Task.baseline_start`` and
    ``Task.budgeted_cost`` (the budget-at-completion basis) to support the SPI /
    SPI(t) earned-value indices; both default to "absent" so prior schedules
    remain valid and EV metrics SKIP (never fabricate) when they are unset.
  * v1.2.0 -- added ``Task.finish`` (the forecast / current scheduled finish, as
    frozen in an export) to support CEI (Current Execution Index, PASEG 10.4.5),
    which reads each period-start version's forecast finish. Defaults to None;
    CEI reports "insufficient data" when it is absent.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bump on ANY change to a model's field set (see test_schema_freeze.py).
SCHEMA_VERSION = "1.2.0"

_STRICT = ConfigDict(frozen=True, extra="forbid", strict=True)


class RelationType(StrEnum):
    """Logic-link type, matching MS Project semantics."""

    FS = "FS"  # finish-to-start
    SS = "SS"  # start-to-start
    FF = "FF"  # finish-to-finish
    SF = "SF"  # start-to-finish


class ConstraintType(StrEnum):
    """Task date-constraint type (MS Project ConstraintType enumeration)."""

    ASAP = "ASAP"  # as soon as possible (default, no constraint)
    ALAP = "ALAP"  # as late as possible
    SNET = "SNET"  # start no earlier than
    SNLT = "SNLT"  # start no later than
    FNET = "FNET"  # finish no earlier than
    FNLT = "FNLT"  # finish no later than
    MSO = "MSO"  # must start on
    MFO = "MFO"  # must finish on


class Relation(BaseModel):
    """A directed logic link between two tasks, keyed by UniqueID.

    ``lag_minutes`` is in working minutes; a negative value is a lead.
    """

    model_config = _STRICT

    predecessor_id: int
    successor_id: int
    type: RelationType = RelationType.FS
    lag_minutes: int = 0


class Task(BaseModel):
    """A single schedule activity. ``unique_id`` is the sole cross-version key."""

    model_config = _STRICT

    unique_id: int
    name: str
    duration_minutes: int = Field(ge=0)  # working minutes; 0 == milestone
    is_milestone: bool = False
    is_summary: bool = False
    constraint_type: ConstraintType = ConstraintType.ASAP
    constraint_date: dt.datetime | None = None
    deadline: dt.datetime | None = None
    # --- tracking / status fields (declared up front to keep the freeze durable) ---
    percent_complete: float = Field(default=0.0, ge=0.0, le=100.0)
    actual_start: dt.datetime | None = None
    actual_finish: dt.datetime | None = None
    finish: dt.datetime | None = None  # v1.2.0: forecast/scheduled finish (for CEI)
    baseline_start: dt.datetime | None = None  # v1.1.0: earned-value PV time-phasing
    baseline_finish: dt.datetime | None = None
    budgeted_cost: float = Field(default=0.0, ge=0.0)  # v1.1.0: BAC, earned-value basis
    resource_names: tuple[str, ...] = ()


class Calendar(BaseModel):
    """Working-time definition for converting working minutes <-> wall clock.

    This slice models a single contiguous working block of
    ``working_minutes_per_day`` per working weekday. Multi-shift calendars,
    lunch breaks, and per-task calendars are deferred (see docs/HAZARDS.md).
    """

    model_config = _STRICT

    name: str = "Standard"
    working_minutes_per_day: int = Field(default=480, gt=0)
    work_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # date.weekday(): Mon=0 .. Sun=6
    holidays: tuple[dt.date, ...] = ()


class Schedule(BaseModel):
    """A complete project schedule at a single status date.

    Comparative forensic analysis orders multiple ``Schedule`` versions by their
    absolute ``status_date`` (the Acumen/SSI ``ProjectTimeNow`` pattern) -- never
    by relative offsets. See CLAUDE.md and docs/REFERENCES.md.
    """

    model_config = _STRICT

    name: str
    project_start: dt.datetime
    status_date: dt.datetime | None = None  # absolute (ProjectTimeNow)
    baseline_finish: dt.datetime | None = None
    calendar: Calendar = Field(default_factory=Calendar)
    tasks: tuple[Task, ...]
    relations: tuple[Relation, ...] = ()

    @model_validator(mode="after")
    def _check_referential_integrity(self) -> Schedule:
        ids = [t.unique_id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate Task.unique_id within a Schedule")
        id_set = set(ids)
        for r in self.relations:
            if r.predecessor_id == r.successor_id:
                raise ValueError(f"self-referential relation on task {r.predecessor_id}")
            if r.predecessor_id not in id_set:
                raise ValueError(
                    f"relation predecessor {r.predecessor_id} is not a task in this schedule"
                )
            if r.successor_id not in id_set:
                raise ValueError(
                    f"relation successor {r.successor_id} is not a task in this schedule"
                )
        return self

    def task_by_id(self, unique_id: int) -> Task:
        for task in self.tasks:
            if task.unique_id == unique_id:
                return task
        raise KeyError(unique_id)
