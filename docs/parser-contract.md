# Parser contract

A parser turns a vendor schedule file into a validated `app.models.Schedule`. The current
build ships a **stub** for MS Project `.mpp` (real parsing needs COM automation that is
unavailable in this sandbox); the function is a **seam** that tests monkeypatch.

## Interface
- `app.parsers.mpp.parse_mpp(file_path: Path) -> Schedule`
- `app.parsers.parse_schedule(file_path: Path) -> Schedule` — dispatches by file extension.

## Output guarantees (what every parser MUST produce)
- A `Schedule` that passes all model validators, so downstream CPM/metrics can trust it:
  - `Task.unique_id` is the identity — unique and stable; never substitute name/external id.
  - Every `Task.calendar_id` references a defined `Calendar`.
  - Every relation endpoint references an existing task; no self-loops.
- `Task.duration_minutes` and `Relation.lag_minutes` are **working-time minutes**.
- `project_start` is a naive datetime (the schedule's own clock).

## Why a stub
Real `.mpp` parsing requires MS Project COM automation (`win32com`) on Windows with MS
Project installed — neither is present here. It is out of scope for this experiment.
Primavera `.xer` / `.xml` parsers are likewise future work.

## Testing the seam
Tests replace `app.parsers.mpp.parse_mpp` via `monkeypatch.setattr` with a synthetic-Schedule
factory (`tests/conftest.make_schedule`). Because `parse_schedule` resolves `mpp.parse_mpp`
at call time, the patch takes effect through the dispatcher.
