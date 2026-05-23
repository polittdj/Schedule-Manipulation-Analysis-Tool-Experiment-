"""Match a project's schedule across versions (status updates) by UniqueID.

Comparative forensic analysis compares the SAME project at different status
dates. Versions are ordered by **absolute** ``status_date`` (the Acumen/SSI
``ProjectTimeNow`` pattern) -- never by relative offsets or by file/input order.
Tasks are matched across versions by ``UniqueID`` ONLY (Commandment 3): row IDs
renumber on insert/delete and names are not unique.

This is a trust-root spine module: it changes the unit of analysis from a single
schedule to an ordered version series that the Phase-5 diff/manipulation modules
consume.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from schedule_forensics.schemas import Schedule


class VersionMatchError(ValueError):
    """Raised when schedule versions cannot be ordered or matched."""


@dataclass(frozen=True)
class VersionDiff:
    """The UniqueID-keyed delta between two consecutive schedule versions."""

    previous_status: dt.datetime
    current_status: dt.datetime
    matched_ids: tuple[int, ...]  # present in both (basis for date/logic comparison)
    added_ids: tuple[int, ...]  # new in current
    deleted_ids: tuple[int, ...]  # present in previous, gone in current


def _status(schedule: Schedule) -> dt.datetime:
    if schedule.status_date is None:
        raise VersionMatchError(f"schedule {schedule.name!r} has no status_date")
    return schedule.status_date


def order_versions(schedules: Sequence[Schedule]) -> tuple[Schedule, ...]:
    """Return the schedules ordered by absolute ``status_date`` (ascending).

    Raises ``VersionMatchError`` if any schedule lacks a ``status_date`` -- the
    comparative anchor. The sort is stable, so versions sharing a status_date
    keep their input order.
    """
    if not schedules:
        raise VersionMatchError("no schedule versions supplied")
    missing = [s.name for s in schedules if s.status_date is None]
    if missing:
        raise VersionMatchError(f"cannot order versions: missing status_date on {missing}")
    return tuple(sorted(schedules, key=_status))


def diff_versions(previous: Schedule, current: Schedule) -> VersionDiff:
    """Compute the UniqueID-keyed delta from ``previous`` to ``current``."""
    prev_ids = {t.unique_id for t in previous.tasks}
    curr_ids = {t.unique_id for t in current.tasks}
    return VersionDiff(
        previous_status=_status(previous),
        current_status=_status(current),
        matched_ids=tuple(sorted(prev_ids & curr_ids)),
        added_ids=tuple(sorted(curr_ids - prev_ids)),
        deleted_ids=tuple(sorted(prev_ids - curr_ids)),
    )


def match_version_series(schedules: Sequence[Schedule]) -> tuple[VersionDiff, ...]:
    """Order versions by status_date, then diff each consecutive pair."""
    ordered = order_versions(schedules)
    return tuple(
        diff_versions(prev, curr) for prev, curr in zip(ordered, ordered[1:], strict=False)
    )
