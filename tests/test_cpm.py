"""M4: CPM engine known-answer tests (hand-computed) + calendar-math invariants.

Conventions: 8h/day (1 day = 480 min), Mon-Fri, no holidays. See docs/cpm-model.md.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.cpm import compute_cpm
from app.cpm.calendar_math import (
    add_working_minutes,
    is_working_day,
    minutes_to_working_days,
    working_minutes_between,
)
from app.exceptions import CPMError
from app.models import RelationType, Schedule
from tests.conftest import make_calendar, make_relation, make_schedule, make_task

DAY = 480


def _example_1() -> Schedule:
    """A->B, A->C, B->D, C->D, D->E (all FS, lag 0). Durations: 2,3,2,4,1 days."""
    tasks = (
        make_task(1, duration_minutes=2 * DAY),
        make_task(2, duration_minutes=3 * DAY),
        make_task(3, duration_minutes=2 * DAY),
        make_task(4, duration_minutes=4 * DAY),
        make_task(5, duration_minutes=1 * DAY),
    )
    relations = (
        make_relation(1, 2),
        make_relation(1, 3),
        make_relation(2, 4),
        make_relation(3, 4),
        make_relation(4, 5),
    )
    return make_schedule(tasks=tasks, relations=relations)


def _example_2() -> Schedule:
    """A->B SS+2d, B->C FF+1d. Durations: 4,6,5 days."""
    tasks = (
        make_task(1, duration_minutes=4 * DAY),
        make_task(2, duration_minutes=6 * DAY),
        make_task(3, duration_minutes=5 * DAY),
    )
    relations = (
        make_relation(1, 2, relation_type=RelationType.SS, lag_minutes=2 * DAY),
        make_relation(2, 3, relation_type=RelationType.FF, lag_minutes=1 * DAY),
    )
    return make_schedule(tasks=tasks, relations=relations)


def test_example_1_merge_and_slack_branch() -> None:
    result = compute_cpm(_example_1())
    assert result.project_finish == 10 * DAY
    a, b, c, d, e = (result.by_id(i) for i in (1, 2, 3, 4, 5))
    assert (a.early_start, a.early_finish) == (0, 2 * DAY)
    assert (b.early_start, b.early_finish) == (2 * DAY, 5 * DAY)
    assert (c.early_start, c.early_finish) == (2 * DAY, 4 * DAY)
    assert (d.early_start, d.early_finish) == (5 * DAY, 9 * DAY)
    assert (e.early_start, e.early_finish) == (9 * DAY, 10 * DAY)
    # C is the only off-critical task: 1 working day of total AND free slack.
    assert c.total_slack == 1 * DAY
    assert c.free_slack == 1 * DAY
    assert a.total_slack == b.total_slack == d.total_slack == e.total_slack == 0
    assert result.critical_path == (1, 2, 4, 5)


def test_example_2_mixed_types_with_lag() -> None:
    result = compute_cpm(_example_2())
    assert result.project_finish == 9 * DAY
    a, b, c = (result.by_id(i) for i in (1, 2, 3))
    assert (a.early_start, a.early_finish) == (0, 4 * DAY)
    assert (b.early_start, b.early_finish) == (2 * DAY, 8 * DAY)
    assert (c.early_start, c.early_finish) == (4 * DAY, 9 * DAY)
    assert a.total_slack == b.total_slack == c.total_slack == 0
    assert a.free_slack == b.free_slack == c.free_slack == 0
    assert result.critical_path == (1, 2, 3)


def test_fs_positive_lag_keeps_both_critical() -> None:
    tasks = (make_task(1, duration_minutes=DAY), make_task(2, duration_minutes=DAY))
    relations = (make_relation(1, 2, lag_minutes=DAY // 2),)
    result = compute_cpm(make_schedule(tasks=tasks, relations=relations))
    assert result.project_finish == 2 * DAY + DAY // 2
    a, b = result.by_id(1), result.by_id(2)
    assert (a.early_start, a.early_finish) == (0, DAY)
    assert (b.early_start, b.early_finish) == (DAY + DAY // 2, 2 * DAY + DAY // 2)
    assert a.late_finish == DAY  # lag is absorbed; A stays critical
    assert a.total_slack == 0 and b.total_slack == 0
    assert result.critical_path == (1, 2)


def test_cycle_raises_cpm_error() -> None:
    tasks = (make_task(1), make_task(2))
    relations = (make_relation(1, 2), make_relation(2, 1))
    schedule = make_schedule(tasks=tasks, relations=relations)
    with pytest.raises(CPMError):
        compute_cpm(schedule)


def test_empty_schedule_raises_cpm_error() -> None:
    schedule = make_schedule(tasks=(), relations=())
    with pytest.raises(CPMError):
        compute_cpm(schedule)


# --- calendar math ---------------------------------------------------------------------


def test_is_working_day() -> None:
    cal = make_calendar(holidays=(date(2026, 1, 1),))  # New Year's Day, a Thursday
    assert is_working_day(cal, date(2026, 1, 5))  # Monday
    assert not is_working_day(cal, date(2026, 1, 3))  # Saturday
    assert not is_working_day(cal, date(2026, 1, 1))  # holiday


def test_add_working_minutes_lands_on_day_close() -> None:
    cal = make_calendar()
    assert add_working_minutes(cal, datetime(2026, 1, 5, 8, 0), DAY) == datetime(2026, 1, 5, 16, 0)


def test_add_working_minutes_skips_weekend() -> None:
    cal = make_calendar()
    # Friday 08:00 + 600 min = Friday's 480 + Monday's 120 -> Monday 10:00.
    result = add_working_minutes(cal, datetime(2026, 1, 9, 8, 0), 600)
    assert result == datetime(2026, 1, 12, 10, 0)


def test_working_minutes_between_round_trips() -> None:
    cal = make_calendar(holidays=(date(2026, 1, 1),))
    start = datetime(2026, 1, 2, 8, 0)  # Friday
    for minutes in (0, 60, DAY, DAY + 1, 2 * DAY, 1000, 5 * DAY):
        assert (
            working_minutes_between(cal, start, add_working_minutes(cal, start, minutes)) == minutes
        )


def test_minutes_to_working_days() -> None:
    cal = make_calendar()  # 8h/day
    assert minutes_to_working_days(DAY, cal) == 1.0
    assert minutes_to_working_days(5 * DAY, cal) == 5.0
