# Parser contract

A parser turns a vendor schedule file into a validated `app.models.Schedule`.

## Interface
- `app.parsers.parse_schedule(file_path: Path) -> Schedule` — dispatches by file extension:
  - `.json` → the tool's own Schedule JSON
  - `.xml` → `app.parsers.msp_xml.parse_msp_xml` (MS Project XML / MSPDI, pure-Python, best-effort)
  - `.xer` → `app.parsers.xer.parse_xer` (Primavera P6 export, pure-Python, best-effort)
  - `.mpp` → `app.parsers.mpp.parse_mpp` (native binary, via **MPXJ** — optional: needs Java 17+ and
    `pip install -r requirements-mpp.txt`; raises with *Save As → XML* guidance if unavailable)
- `POST /upload` (web) accepts a `.xml`/`.xer`/`.mpp`/`.json` file and returns the parsed Schedule JSON.

The `.xml`/`.xer` importers are **best-effort** (no real vendor samples were available when
written) — see `FIDELITY-COMPROMISE-importers.md`. They were validated against crafted samples
in `tests/test_parsers_native.py`.

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
