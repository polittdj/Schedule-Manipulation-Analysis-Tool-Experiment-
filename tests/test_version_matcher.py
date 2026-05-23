"""Version-matcher tests: absolute-status-date ordering + UniqueID-keyed deltas.

Expected sets are hand-derived; perturbation tests confirm the deltas actually
respond to added/removed tasks (H-VACUOUS-TEST).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pytest

from schedule_forensics.schemas import Schedule, Task
from schedule_forensics.version_matcher import (
    VersionMatchError,
    diff_versions,
    match_version_series,
    order_versions,
)

_START = dt.datetime(2025, 1, 6, 8)


def _t(uid: int, name: str = "T") -> Task:
    return Task(unique_id=uid, name=name, duration_minutes=480)


def _v(status: dt.datetime | None, tasks: Iterable[Task], name: str = "P") -> Schedule:
    return Schedule(name=name, project_start=_START, status_date=status, tasks=tuple(tasks))


def test_order_by_status_date_not_input_order() -> None:
    march = _v(dt.datetime(2025, 3, 1), [_t(1)], name="March")
    jan = _v(dt.datetime(2025, 1, 1), [_t(1)], name="Jan")
    feb = _v(dt.datetime(2025, 2, 1), [_t(1)], name="Feb")
    ordered = order_versions([march, jan, feb])
    assert [s.name for s in ordered] == ["Jan", "Feb", "March"]


def test_order_is_stable_on_status_date_tie() -> None:
    # Two versions sharing a status_date keep their INPUT order (documented stable
    # sort), so a tie never silently reorders the comparative series.
    same = dt.datetime(2025, 3, 1)
    a = _v(same, [_t(1)], name="A")
    b = _v(same, [_t(2)], name="B")
    assert [s.name for s in order_versions([a, b])] == ["A", "B"]
    assert [s.name for s in order_versions([b, a])] == ["B", "A"]


def test_order_raises_without_status_date() -> None:
    with_status = _v(dt.datetime(2025, 1, 1), [_t(1)])
    without_status = _v(None, [_t(1)], name="NoStatus")
    with pytest.raises(VersionMatchError, match="status_date"):
        order_versions([with_status, without_status])


def test_order_empty_raises() -> None:
    with pytest.raises(VersionMatchError):
        order_versions([])


def test_diff_added_deleted_matched() -> None:
    prev = _v(dt.datetime(2025, 1, 1), [_t(1), _t(2), _t(3)])
    curr = _v(dt.datetime(2025, 2, 1), [_t(2), _t(3), _t(4)])
    diff = diff_versions(prev, curr)
    assert diff.matched_ids == (2, 3)
    assert diff.added_ids == (4,)
    assert diff.deleted_ids == (1,)
    assert diff.previous_status == dt.datetime(2025, 1, 1)
    assert diff.current_status == dt.datetime(2025, 2, 1)


def test_match_is_by_unique_id_not_name() -> None:
    # Same UniqueID, different name -> still matched (a renamed task is not new/deleted).
    prev = _v(dt.datetime(2025, 1, 1), [_t(1, "Old Name")])
    curr = _v(dt.datetime(2025, 2, 1), [_t(1, "New Name")])
    diff = diff_versions(prev, curr)
    assert diff.matched_ids == (1,)
    assert diff.added_ids == ()
    assert diff.deleted_ids == ()


def test_series_orders_then_diffs_consecutive_pairs() -> None:
    v1 = _v(dt.datetime(2025, 1, 1), [_t(1)])
    v2 = _v(dt.datetime(2025, 2, 1), [_t(1), _t(2)])
    v3 = _v(dt.datetime(2025, 3, 1), [_t(2)])
    diffs = match_version_series([v3, v1, v2])  # deliberately unordered input
    assert len(diffs) == 2
    assert diffs[0].added_ids == (2,)  # v1 -> v2 adds task 2
    assert diffs[1].deleted_ids == (1,)  # v2 -> v3 deletes task 1


def test_single_version_series_is_empty() -> None:
    assert match_version_series([_v(dt.datetime(2025, 1, 1), [_t(1)])]) == ()


def test_perturbation_adding_task_changes_delta() -> None:
    prev = _v(dt.datetime(2025, 1, 1), [_t(1)])
    assert diff_versions(prev, _v(dt.datetime(2025, 2, 1), [_t(1)])).added_ids == ()
    assert diff_versions(prev, _v(dt.datetime(2025, 2, 1), [_t(1), _t(99)])).added_ids == (99,)
