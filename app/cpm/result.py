"""CPM result types — frozen stdlib dataclasses (computed by trusted code; no validation
needed, only immutability and value-equality)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TaskTiming:
    """Per-task CPM timing, all in working-minute offsets from the project start."""

    unique_id: int
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    total_slack: int
    free_slack: int


@dataclass(frozen=True, slots=True)
class CPMResult:
    """The result of a CPM pass over a schedule.

    ``project_finish`` is the working-minute offset of the latest early finish.
    ``critical_path`` is the UniqueIDs whose total slack is zero, ascending. A tuple (not a
    list) so the result is genuinely immutable.
    """

    project_start: datetime
    project_finish: int
    timings: tuple[TaskTiming, ...]
    critical_path: tuple[int, ...]

    def by_id(self, unique_id: int) -> TaskTiming:
        for timing in self.timings:
            if timing.unique_id == unique_id:
                return timing
        raise KeyError(unique_id)
