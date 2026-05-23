"""Tests for the optional Windows-only COM ``.mpp`` importer.

This whole module runs ON LINUX. That is the point: the COM importer is split so
the *mapping* (:func:`schedule_from_com_project`) is a PURE function exercised
here against a FAKE COM project object, while only the live connection
(:func:`parse_mpp_via_com`) is Windows-bound. Off-Windows the driver actively
RAISES :class:`ComUnavailableError` -- we assert that here rather than skipping,
which proves the guard works.

The fake objects below duck-type the slice of the MS Project COM object model the
importer reads (``.Name``/``.StatusDate``/``.ProjectStart``/``.Tasks``; per task
``.UniqueID``/``.Duration``/``.ConstraintType``/...; per dependency
``.From``/``.To``/``.Type``/``.Lag``). Every asserted expectation is HAND-COMPUTED
from these fakes -- no value is read back from the importer to define its own
oracle (anti-vacuous-test discipline, docs/HAZARDS.md H-VACUOUS-TEST).
"""

from __future__ import annotations

import datetime as dt

import pytest

from schedule_forensics.importers.com_msproject import (
    ComUnavailableError,
    schedule_from_com_project,
)
from schedule_forensics.schemas import ConstraintType, RelationType


# --------------------------------------------------------------------------- #
# Fake COM object model (plain Python; duck-typed to the slice we read).
# --------------------------------------------------------------------------- #
class FakeDependency:
    """A fake MS Project ``TaskDependency``: links a ``From`` task to a ``To`` task."""

    def __init__(self, from_task: object, to_task: object, type_code: int, lag: float) -> None:
        self.From = from_task
        self.To = to_task
        self.Type = type_code
        self.Lag = lag


class FakeResource:
    def __init__(self, name: str) -> None:
        self.Name = name


class FakeTask:
    """A fake MS Project ``Task``. Only the attributes the importer reads are set."""

    def __init__(
        self,
        *,
        unique_id: int,
        name: str,
        duration: float = 0.0,
        milestone: bool = False,
        summary: bool = False,
        constraint_type: int = 0,
        constraint_date: object = None,
        deadline: object = None,
        percent_complete: float = 0.0,
        actual_start: object = None,
        actual_finish: object = None,
        baseline_start: object = None,
        baseline_finish: object = None,
        baseline_cost: float = 0.0,
        resources: list[FakeResource] | None = None,
    ) -> None:
        self.UniqueID = unique_id
        self.Name = name
        self.Duration = duration
        self.Milestone = milestone
        self.Summary = summary
        self.ConstraintType = constraint_type
        self.ConstraintDate = constraint_date
        self.Deadline = deadline
        self.PercentComplete = percent_complete
        self.ActualStart = actual_start
        self.ActualFinish = actual_finish
        self.BaselineStart = baseline_start
        self.BaselineFinish = baseline_finish
        self.BaselineCost = baseline_cost
        self.Resources = resources if resources is not None else []
        self.TaskDependencies: list[FakeDependency] = []


class FakeProject:
    """A fake MS Project ``Project``. ``Tasks`` may include ``None`` blank rows."""

    def __init__(
        self,
        *,
        name: str,
        project_start: object,
        status_date: object = None,
        baseline_finish: object = None,
        tasks: list[object] | None = None,
    ) -> None:
        self.Name = name
        self.ProjectStart = project_start
        self.StatusDate = status_date
        self.BaselineFinish = baseline_finish
        self.Tasks = tasks if tasks is not None else []


def _build_fake_project() -> FakeProject:
    """A 3-task network with one ``None`` blank row and a single FS predecessor link.

    Layout (hand-computed expectations follow each line):
      * task 1 "Foundation": 960 min duration, SNLT (code 5), 50% complete,
        actual start 2025-01-06 08:00, NA constraint date (sentinel string).
      * task 2 "Framing": 480 min, ASAP, predecessor link 1 ->(FS, lag 120) 2.
      * task 3 milestone "Done": 0 min, milestone, with a deadline.
      * a ``None`` entry between tasks 2 and 3 (blank row -- must be skipped).
    """
    t1 = FakeTask(
        unique_id=1,
        name="Foundation",
        duration=960.0,  # minutes (gotcha 5): 960 == 2 days @ 480/day
        constraint_type=5,  # SNLT
        constraint_date="NA",  # MS Project NA sentinel -> None (gotcha 6)
        percent_complete=50.0,
        actual_start=dt.datetime(2025, 1, 6, 8, 0),
        baseline_cost=1000.0,
        resources=[FakeResource("Crew A"), FakeResource("Crane")],
    )
    t2 = FakeTask(
        unique_id=2,
        name="Framing",
        duration=480.0,  # minutes -> 1 day
        constraint_type=0,  # ASAP
    )
    t3 = FakeTask(
        unique_id=3,
        name="Done",
        duration=0.0,
        milestone=True,
        # A pre-1985 sentinel datetime must normalize to None (gotcha 6); use a
        # real deadline to prove the date IS read when valid.
        deadline=dt.datetime(2025, 2, 1, 17, 0),
    )
    # Single dependency, attached to BOTH endpoints (mirrors the live COM model,
    # where each task exposes the same TaskDependency). The importer must emit the
    # link exactly ONCE -- it only keeps a dep where THIS task is the .To side.
    dep_1_2 = FakeDependency(from_task=t1, to_task=t2, type_code=1, lag=120.0)  # FS, +120 min
    t1.TaskDependencies = [dep_1_2]
    t2.TaskDependencies = [dep_1_2]

    return FakeProject(
        name="Forensic Sample COM",
        project_start=dt.datetime(2025, 1, 6, 8, 0),
        status_date=dt.datetime(2025, 1, 20, 17, 0),
        baseline_finish=dt.datetime(2025, 3, 1, 17, 0),
        tasks=[t1, t2, None, t3],  # the None is a blank row (gotcha 4)
    )


# --------------------------------------------------------------------------- #
# Pure-mapping tests (run on Linux against the fake COM object).
# --------------------------------------------------------------------------- #
def test_blank_row_is_skipped_and_counts_match() -> None:
    schedule = schedule_from_com_project(_build_fake_project())
    # 4 entries in .Tasks, one is None (blank row, gotcha 4) -> 3 real tasks.
    assert len(schedule.tasks) == 3
    assert {t.unique_id for t in schedule.tasks} == {1, 2, 3}


def test_project_level_fields() -> None:
    schedule = schedule_from_com_project(_build_fake_project())
    assert schedule.name == "Forensic Sample COM"
    assert schedule.project_start == dt.datetime(2025, 1, 6, 8, 0)
    assert schedule.status_date == dt.datetime(2025, 1, 20, 17, 0)
    assert schedule.baseline_finish == dt.datetime(2025, 3, 1, 17, 0)


def test_duration_read_as_minutes() -> None:
    schedule = schedule_from_com_project(_build_fake_project())
    by_id = {t.unique_id: t for t in schedule.tasks}
    # COM Duration is in minutes (gotcha 5); read directly, no scaling.
    assert by_id[1].duration_minutes == 960
    assert by_id[2].duration_minutes == 480
    assert by_id[3].duration_minutes == 0


def test_constraint_code_5_maps_to_snlt() -> None:
    schedule = schedule_from_com_project(_build_fake_project())
    by_id = {t.unique_id: t for t in schedule.tasks}
    assert by_id[1].constraint_type is ConstraintType.SNLT  # code 5
    assert by_id[2].constraint_type is ConstraintType.ASAP  # code 0


def test_milestone_and_status_fields() -> None:
    schedule = schedule_from_com_project(_build_fake_project())
    by_id = {t.unique_id: t for t in schedule.tasks}
    assert by_id[3].is_milestone is True
    assert by_id[1].is_milestone is False
    assert by_id[1].percent_complete == 50.0
    assert by_id[1].actual_start == dt.datetime(2025, 1, 6, 8, 0)
    assert by_id[1].budgeted_cost == 1000.0
    assert by_id[1].resource_names == ("Crew A", "Crane")


def test_na_constraint_date_becomes_none_but_real_deadline_is_read() -> None:
    schedule = schedule_from_com_project(_build_fake_project())
    by_id = {t.unique_id: t for t in schedule.tasks}
    # "NA" sentinel string -> None (gotcha 6).
    assert by_id[1].constraint_date is None
    # A valid deadline IS read (proves None is from the sentinel, not a constant).
    assert by_id[3].deadline == dt.datetime(2025, 2, 1, 17, 0)


def test_pre_1985_sentinel_date_becomes_none() -> None:
    # A pre-1985 datetime is MS Project's "no date" sentinel and must map to None
    # (gotcha 6), distinct from a genuinely set date.
    proj = _build_fake_project()
    by_uid = {t.UniqueID: t for t in proj.Tasks if t is not None}
    by_uid[2].ActualStart = dt.datetime(1984, 1, 1, 0, 0)  # sentinel
    schedule = schedule_from_com_project(proj)
    assert {t.unique_id: t for t in schedule.tasks}[2].actual_start is None


def test_predecessor_relation_mapped_once_with_type_and_lag() -> None:
    schedule = schedule_from_com_project(_build_fake_project())
    # The single dependency appears on both endpoints; the importer must emit it
    # EXACTLY once, keyed off the successor (the .To side).
    assert len(schedule.relations) == 1
    rel = schedule.relations[0]
    assert rel.predecessor_id == 1
    assert rel.successor_id == 2
    assert rel.type is RelationType.FS  # dependency code 1 -> FS
    assert rel.lag_minutes == 120  # COM Lag is in minutes (gotcha 5)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, ConstraintType.ASAP),
        (1, ConstraintType.ALAP),
        (2, ConstraintType.MSO),
        (3, ConstraintType.MFO),
        (4, ConstraintType.SNET),
        (5, ConstraintType.SNLT),
        (6, ConstraintType.FNET),
        (7, ConstraintType.FNLT),
    ],
)
def test_constraint_code_perturbation_changes_mapping(code: int, expected: ConstraintType) -> None:
    # Perturbation discipline (H-VACUOUS-TEST): changing a fake task's
    # ConstraintType code must change the mapped enum -- proving the field is
    # actually read, not hardcoded. Each documented code maps to its enum.
    proj = _build_fake_project()
    by_uid = {t.UniqueID: t for t in proj.Tasks if t is not None}
    by_uid[2].ConstraintType = code
    schedule = schedule_from_com_project(proj)
    assert {t.unique_id: t for t in schedule.tasks}[2].constraint_type is expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, RelationType.FF),
        (1, RelationType.FS),
        (2, RelationType.SF),
        (3, RelationType.SS),
    ],
)
def test_dependency_type_perturbation_changes_mapping(code: int, expected: RelationType) -> None:
    # Perturbing the dependency Type code must change the mapped RelationType.
    proj = _build_fake_project()
    by_uid = {t.UniqueID: t for t in proj.Tasks if t is not None}
    # Both endpoints share the same dependency object; mutate it once.
    by_uid[2].TaskDependencies[0].Type = code
    schedule = schedule_from_com_project(proj)
    assert schedule.relations[0].type is expected


def test_finish_field_is_read() -> None:
    # COM Task.Finish -> Task.finish (forecast finish, for CEI). The fake has no
    # Finish attr by default (-> None tolerated); set it to prove it is read.
    proj = _build_fake_project()
    by_uid = {t.UniqueID: t for t in proj.Tasks if t is not None}
    by_uid[1].Finish = dt.datetime(2025, 6, 30, 17)
    schedule = schedule_from_com_project(proj)
    assert {t.unique_id: t for t in schedule.tasks}[1].finish == dt.datetime(2025, 6, 30, 17)


def test_none_fields_tolerated_everywhere() -> None:
    # Commandment 5: a task with essentially all-None optional fields must still
    # map (defaults applied), not crash.
    proj = FakeProject(
        name="Sparse",
        project_start=dt.datetime(2025, 1, 6, 8, 0),
        tasks=[
            FakeTask(
                unique_id=10,
                name="Sparse Task",
                duration=0.0,
                constraint_date=None,
                deadline=None,
                actual_start=None,
                actual_finish=None,
                baseline_start=None,
                baseline_finish=None,
                resources=[],
            )
        ],
    )
    schedule = schedule_from_com_project(proj)
    task = schedule.tasks[0]
    assert task.unique_id == 10
    assert task.constraint_type is ConstraintType.ASAP
    assert task.constraint_date is None
    assert task.deadline is None
    assert task.resource_names == ()
    assert task.percent_complete == 0.0
    assert task.budgeted_cost == 0.0


# --------------------------------------------------------------------------- #
# Windows-only driver guard (runs and PASSES on Linux by raising).
# --------------------------------------------------------------------------- #
def test_parse_mpp_via_com_raises_off_windows() -> None:
    # On this (non-Windows) platform win32com/pythoncom are not importable, so the
    # driver must raise ComUnavailableError. NOT skipped -- it actively passes here,
    # proving the import guard (Commandment 1; docs/HAZARDS.md H-NO-COM-HERE).
    from schedule_forensics.importers.com_msproject import parse_mpp_via_com

    with pytest.raises(ComUnavailableError):
        parse_mpp_via_com("anything.mpp")
