"""Tests for time-phase slicing of a status-dated schedule series.

Each test perturbs one thing and asserts the specific phase boundary that must
result, so the suite is non-vacuous: a wrong ordering or a wrong "first phase"
rule would fail a named test. The convention under test (from phases.py):
  * Phase 1 = [earliest_date(first schedule), first.status_date]
  * Phase k = [(k-1).status_date, k.status_date]
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from schedule_forensics.phases import Phase, compute_phases, earliest_date
from schedule_forensics.schemas import Schedule, Task
from schedule_forensics.version_matcher import VersionMatchError

START = dt.datetime(2025, 1, 6, 8, 0, 0)


def _task(uid: int, **over: object) -> Task:
    fields: dict[str, object] = {"unique_id": uid, "name": f"T{uid}", "duration_minutes": 480}
    fields.update(over)
    return Task(**fields)  # type: ignore[arg-type]


def _sched(
    name: str,
    status: dt.datetime | None,
    *,
    project_start: dt.datetime = START,
    tasks: tuple[Task, ...] = (),
) -> Schedule:
    return Schedule(
        name=name,
        project_start=project_start,
        status_date=status,
        tasks=tasks or (_task(1),),
    )


def test_empty_input_raises() -> None:
    with pytest.raises(VersionMatchError):
        compute_phases([])


def test_missing_status_date_raises() -> None:
    with pytest.raises(VersionMatchError):
        compute_phases([_sched("no status", None)])


def test_single_schedule_yields_one_phase_from_earliest_to_status() -> None:
    s = _sched("only", dt.datetime(2025, 3, 1, 17, 0))
    phases = compute_phases([s])
    assert len(phases) == 1
    p = phases[0]
    assert p.index == 1
    assert p.schedule_name == "only"
    assert p.phase_start == START  # project_start when no task date is earlier
    assert p.phase_end == dt.datetime(2025, 3, 1, 17, 0)


def test_first_phase_uses_an_earlier_task_date_when_present() -> None:
    # An actuals task carries a date earlier than project_start; the first phase
    # must anchor to that earliest date, not to project_start.
    early = dt.datetime(2024, 12, 1, 8, 0)
    t = _task(1, actual_start=early)
    s = _sched("with early actual", dt.datetime(2025, 2, 1), tasks=(t,))
    assert earliest_date(s) == early
    phases = compute_phases([s])
    assert phases[0].phase_start == early


def test_three_versions_out_of_order_become_chronological_phases() -> None:
    s_mar = _sched("S_Mar", dt.datetime(2025, 3, 1))
    s_jan = _sched("S_Jan", dt.datetime(2025, 1, 31))
    s_feb = _sched("S_Feb", dt.datetime(2025, 2, 15))
    phases = compute_phases([s_mar, s_jan, s_feb])  # input scrambled

    # 3 phases, chronological, with the prescribed boundaries.
    assert [p.schedule_name for p in phases] == ["S_Jan", "S_Feb", "S_Mar"]
    assert [p.index for p in phases] == [1, 2, 3]
    # Phase 1 starts at the earliest date in the first schedule (== project_start here).
    assert phases[0].phase_start == START
    assert phases[0].phase_end == dt.datetime(2025, 1, 31)
    # Phase 2 starts at phase 1's end (the prior status date).
    assert phases[1].phase_start == dt.datetime(2025, 1, 31)
    assert phases[1].phase_end == dt.datetime(2025, 2, 15)
    # Phase 3 starts at phase 2's end.
    assert phases[2].phase_start == dt.datetime(2025, 2, 15)
    assert phases[2].phase_end == dt.datetime(2025, 3, 1)


def test_phase_duration_days_is_calendar_days() -> None:
    # Same time-of-day as START so the calendar-day deltas come out exact.
    s1 = _sched("a", dt.datetime(2025, 1, 16, 8, 0))  # 10 days after START
    s2 = _sched("b", dt.datetime(2025, 1, 26, 8, 0))  # +10 more days
    phases = compute_phases([s1, s2])
    assert phases[0].duration_days == pytest.approx(10.0, abs=1e-6)
    assert phases[1].duration_days == pytest.approx(10.0, abs=1e-6)


def test_twenty_versions_yields_twenty_chronological_phases() -> None:
    # The requirement specifically allows up to 20 .mpp files; verify the engine
    # handles 20 versions and produces 20 contiguous phases.
    schedules = [_sched(f"v{i:02d}", START + dt.timedelta(days=i + 1)) for i in range(20)]
    phases = compute_phases(schedules)
    assert len(phases) == 20
    assert [p.index for p in phases] == list(range(1, 21))
    # Each phase's end equals the next phase's start (contiguous), except phase 1
    # which starts at the earliest date of the earliest schedule.
    assert phases[0].phase_start == START
    for prev, curr in zip(phases[:-1], phases[1:], strict=True):
        assert prev.phase_end == curr.phase_start


def test_phase_is_immutable_dataclass() -> None:
    p = Phase(index=1, schedule_name="x", phase_start=START, phase_end=START)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.index = 2  # type: ignore[misc]
