"""CPM tests for SS/FF/SF link types and the fail-closed constraint/deadline guard.

All expected offsets are hand-computed (480 working minutes per day).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pytest

from schedule_forensics.cpm import CPMError, compute_cpm
from schedule_forensics.schemas import ConstraintType, Relation, RelationType, Schedule, Task

_START = dt.datetime(2025, 1, 6, 8)


def _task(uid: int, dur: int, **kwargs: object) -> Task:
    return Task(unique_id=uid, name=f"T{uid}", duration_minutes=dur, **kwargs)  # type: ignore[arg-type]


def _rel(pred: int, succ: int, rel_type: RelationType = RelationType.FS, lag: int = 0) -> Relation:
    return Relation(predecessor_id=pred, successor_id=succ, type=rel_type, lag_minutes=lag)


def _sched(tasks: Iterable[Task], relations: Iterable[Relation] = ()) -> Schedule:
    return Schedule(name="t", project_start=_START, tasks=tuple(tasks), relations=tuple(relations))


def test_ss_link_starts_with_predecessor() -> None:
    # A(2d) ->SS(0) B(1d): B starts when A starts.
    result = compute_cpm(_sched([_task(1, 960), _task(2, 480)], [_rel(1, 2, RelationType.SS)]))
    assert result.timings[2].early_start == 0
    assert result.timings[2].early_finish == 480
    assert result.project_finish == 960


def test_ss_link_with_lag() -> None:
    # A(2d) ->SS(1d) B(1d): B starts one working day after A starts.
    result = compute_cpm(_sched([_task(1, 960), _task(2, 480)], [_rel(1, 2, RelationType.SS, 480)]))
    assert result.timings[2].early_start == 480
    assert result.timings[2].early_finish == 960


def test_ff_link_finishes_with_predecessor() -> None:
    # A(2d) ->FF(0) B(1d): B finishes when A finishes (960) -> B starts at 480.
    result = compute_cpm(_sched([_task(1, 960), _task(2, 480)], [_rel(1, 2, RelationType.FF)]))
    assert result.timings[2].early_finish == 960
    assert result.timings[2].early_start == 480
    assert result.project_finish == 960


def test_sf_link_finishes_when_predecessor_starts() -> None:
    # Pre(2d) ->FS A(1d) pushes A.ES to 960; A ->SF(0) S(1d): S must finish >= A.ES (960).
    result = compute_cpm(
        _sched(
            [_task(10, 960), _task(1, 480), _task(2, 480)],
            [_rel(10, 1, RelationType.FS), _rel(1, 2, RelationType.SF)],
        )
    )
    assert result.timings[1].early_start == 960  # A pushed by its predecessor
    assert result.timings[2].early_finish == 960  # S finishes when A starts
    assert result.timings[2].early_start == 480


def test_ff_link_with_lag() -> None:
    # A(1d) ->FF(+1d) B(1d): B finishes one working day after A finishes.
    result = compute_cpm(_sched([_task(1, 480), _task(2, 480)], [_rel(1, 2, RelationType.FF, 480)]))
    assert result.timings[2].early_finish == 960  # A.EF(480) + 480 lag
    assert result.timings[2].early_start == 480
    assert result.project_finish == 960


def test_fs_lead_pulls_successor_earlier() -> None:
    # A(1d) ->FS(-0.5d lead) B(1d): a negative lag (lead) lets B start before A finishes.
    result = compute_cpm(
        _sched([_task(1, 480), _task(2, 480)], [_rel(1, 2, RelationType.FS, -240)])
    )
    assert result.timings[2].early_start == 240  # A.EF(480) - 240 lead
    assert result.timings[2].early_finish == 720
    assert result.project_finish == 720


def test_disconnected_components_finish_at_max() -> None:
    # Two independent tasks (no relations): project finish is the max (960). The
    # shorter task floats to that finish; only the longer task is critical.
    result = compute_cpm(_sched([_task(1, 480), _task(2, 960)]))
    assert result.project_finish == 960
    assert result.timings[1].total_float == 480  # shorter task has slack to the finish
    assert result.timings[2].total_float == 0
    assert result.timings[2].is_critical is True


def test_ss_perturbation_changes_start() -> None:
    # Mutation discipline: adding lag to the SS link must shift the successor.
    base = _sched([_task(1, 960), _task(2, 480)], [_rel(1, 2, RelationType.SS)])
    assert compute_cpm(base).timings[2].early_start == 0
    lagged = _sched([_task(1, 960), _task(2, 480)], [_rel(1, 2, RelationType.SS, 480)])
    assert compute_cpm(lagged).timings[2].early_start == 480


def test_pin_constraint_raises_until_supported() -> None:
    # MSO/MFO/ALAP are deferred -- the engine refuses rather than mis-schedule.
    schedule = _sched([_task(1, 480, constraint_type=ConstraintType.MSO)])
    with pytest.raises(CPMError, match="not yet honored"):
        compute_cpm(schedule)
