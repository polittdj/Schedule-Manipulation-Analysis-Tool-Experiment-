"""Time-phase slicing of a status-dated schedule series.

For a forensic comparative review the operator uploads N versions of the same
project (each a different ``status_date``) and wants to see them as a sequence
of TIME PHASES, one per version, in chronological order. The convention this
module implements:

  * **Phase 1** (the earliest version) starts at the EARLIEST DATE in that
    schedule and ends at THAT schedule's ``status_date``.
  * **Phase k > 1** starts at the PRIOR version's ``status_date`` and ends at
    the CURRENT version's ``status_date``.

So N status-dated versions yield N phases, in chronological order. This is a
companion to ``cei.py`` -- CEI's *periods* are the N-1 inter-version intervals
(``(prior.status_date, current.status_date]``); the PHASES here additionally
include a Phase 1 bounded by the first schedule's own earliest date, which is
what the operator's forensic narrative needs.

Ordering reuses ``version_matcher.order_versions`` so the "ordered by absolute
``status_date``" rule (the Acumen/SSI ``ProjectTimeNow`` pattern) is the SINGLE
source of truth (LAW 2): any schedule missing a status_date is rejected here
just as it would be for CEI / diff / trend.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from schedule_forensics.schemas import Schedule
from schedule_forensics.version_matcher import order_versions


@dataclass(frozen=True)
class Phase:
    """One time-bounded phase derived from a status-dated schedule version."""

    index: int  # 1-based chronological position (Phase 1, 2, ...)
    schedule_name: str
    phase_start: dt.datetime
    phase_end: dt.datetime  # always equals the schedule's status_date

    @property
    def duration_days(self) -> float:
        """Phase length in real (calendar) days. Negative if start > end (data error)."""
        return (self.phase_end - self.phase_start).total_seconds() / 86400.0


def earliest_date(schedule: Schedule) -> dt.datetime:
    """Return the earliest datetime anchored anywhere in *schedule*.

    Considers ``project_start`` and every non-``None`` task datetime field
    (start/finish/baseline/actual/constraint/deadline). In a well-formed MS
    Project schedule this is ``project_start``; the broader scan is robust to
    schedules whose project anchor was set late but contain earlier task dates
    (e.g. legacy actuals).
    """
    earliest = schedule.project_start
    for task in schedule.tasks:
        for value in (
            task.actual_start,
            task.actual_finish,
            task.baseline_start,
            task.baseline_finish,
            task.constraint_date,
            task.deadline,
            task.finish,
        ):
            if value is not None and value < earliest:
                earliest = value
    return earliest


def compute_phases(schedules: Sequence[Schedule]) -> tuple[Phase, ...]:
    """Order the schedules by absolute ``status_date`` and slice them into phases.

    Returns one :class:`Phase` per schedule (so N versions yield N phases) in
    chronological order. Raises :class:`schedule_forensics.version_matcher.
    VersionMatchError` if *schedules* is empty or any version lacks a
    ``status_date`` (Acumen/SSI ``ProjectTimeNow`` is the comparative anchor).
    """
    ordered = order_versions(schedules)
    phases: list[Phase] = []
    prior_status: dt.datetime | None = None
    for idx, sched in enumerate(ordered, start=1):
        # ``status_date`` is guaranteed non-None by ``order_versions``.
        assert sched.status_date is not None
        phase_start = earliest_date(sched) if idx == 1 else prior_status
        assert phase_start is not None  # set on idx==1 above; carried forward thereafter
        phases.append(
            Phase(
                index=idx,
                schedule_name=sched.name,
                phase_start=phase_start,
                phase_end=sched.status_date,
            )
        )
        prior_status = sched.status_date
    return tuple(phases)
