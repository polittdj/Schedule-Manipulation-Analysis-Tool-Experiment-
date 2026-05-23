"""Schema freeze guard (H-DRIFT-2): the field sets are the single source of truth.

The schema is FROZEN. This test fails if any model's field set changes, forcing a
deliberate ``SCHEMA_VERSION`` bump + change-control review in the same change
rather than silent drift that would invalidate downstream modules.
"""

from __future__ import annotations

from schedule_forensics.schemas import (
    SCHEMA_VERSION,
    Calendar,
    Relation,
    Schedule,
    Task,
)


def test_schema_version_is_frozen() -> None:
    assert SCHEMA_VERSION == "1.2.0"


def test_schedule_field_set_is_frozen() -> None:
    assert set(Schedule.model_fields) == {
        "name",
        "project_start",
        "status_date",
        "baseline_finish",
        "calendar",
        "tasks",
        "relations",
    }


def test_task_field_set_is_frozen() -> None:
    assert set(Task.model_fields) == {
        "unique_id",
        "name",
        "duration_minutes",
        "is_milestone",
        "is_summary",
        "constraint_type",
        "constraint_date",
        "deadline",
        "percent_complete",
        "actual_start",
        "actual_finish",
        "finish",
        "baseline_start",
        "baseline_finish",
        "budgeted_cost",
        "resource_names",
    }


def test_relation_field_set_is_frozen() -> None:
    assert set(Relation.model_fields) == {
        "predecessor_id",
        "successor_id",
        "type",
        "lag_minutes",
    }


def test_calendar_field_set_is_frozen() -> None:
    assert set(Calendar.model_fields) == {
        "name",
        "working_minutes_per_day",
        "work_weekdays",
        "holidays",
    }
