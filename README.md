# Schedule Manipulation Analysis Tool (Experiment)

A forensic schedule-analysis tool. It ingests project schedules (MS Project / Primavera)
and runs DCMA-14 schedule-quality metrics and critical-path (CPM) analysis. This repository
is an **autonomous build experiment** — see [`EXPERIMENT-REPORT.md`](EXPERIMENT-REPORT.md).

> Fidelity-first: results aim to match Acumen Fuse / Steelray / MS Project semantics.
> Speed and elegance are tiebreakers, never overrides.

## Status (milestones)
- **M1 — Scaffolding:** Flask app factory, 500 MB upload guard + 413 handler, CI. ← current
- M2 — Pydantic data model (Schedule / Task / Relation / Calendar).
- M3 — Parser seam (stub; real `.mpp` parsing needs MS Project COM and is out of scope here).
- M4 — CPM engine (forward/backward pass, total/free slack, critical path).
- M5 — DCMA metrics 1–4 (missing logic, leads, lags, relationship types).

## Layout
- `app/` — application package: `create_app` factory, config, error handlers, routes.
- `tests/` — pytest suite.
- `docs/` — design notes.

## Development
```sh
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && mypy app/ && pytest -q
```

## Running
```sh
flask --app "app:create_app" run        # http://localhost:5000/health

# Analyze a schedule (JSON Schedule body in -> CPM + DCMA metrics report out):
curl -X POST http://localhost:5000/analyze \
  -H 'Content-Type: application/json' --data-binary @schedule.json
```
`POST /analyze` validates a JSON `Schedule`, runs the CPM engine and the DCMA metrics, and returns
per-task timings (ES/EF/LS/LF/slack), the critical path, project finish (working days), and
per-metric results.

## Security note
Schedule files (`*.mpp`, `*.xer`, `*.xml`) may carry Controlled Unclassified Information
and are git-ignored. Do not commit them.
