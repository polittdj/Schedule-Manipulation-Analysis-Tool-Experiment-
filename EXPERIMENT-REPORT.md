# EXPERIMENT REPORT — Schedule Manipulation Analysis Tool (Autonomous M1–M5)

> Rolling final report. The most recently committed version is the experiment's
> output. Updated at least every ~20 min of work and at every PR merge.

## 1. Session start
- **Session start commit (SHA at start):** `506b3d9` ("Initial commit", README only).
- **Date:** 2026-05-20.
- **Branch model:** per-milestone feature branches → PR → `main` (see §5 STUCK-branch-strategy).
- **Reference docs:** `/mnt/project/BUILD-PLAN.md` and DCMA PDFs/XLSX were **unavailable**
  this session (see §5 STUCK-build-plan-unavailable). Built from the embedded milestone
  summaries, in my own voice — zero verbatim-copy risk.

## 2. Milestones completed
_(PR # + merge commit SHA recorded as they merge.)_
- **M1 — Scaffolding** — PR #1, squash-merged to `main` as **`d0ba6cf`**. Flask app-factory,
  500 MB upload guard + 413 handler, flask-free exception base, pinned reqs, ruff/mypy-strict/pytest,
  GitHub Actions CI. CI green in 16s; 3 smoke tests pass. (Branch `m1-scaffolding`, pre-squash `96845c7`.)
- **M2 — Pydantic data model** — PR #2, squash-merged to `main` as **`1f98960`**. Frozen/strict/
  extra-forbid `Calendar`/`Task`/`Relation`/`Schedule`; sorted-tuple collections; referential-integrity
  validator; UniqueID identity; byte-equal JSON round-trip. CI green in 20s; 12 new tests (15 total).
- **M3 — Parser stub** — PR #3, squash-merged to `main` as **`fbf1fe8`**. `parse_mpp` stub raises
  `NotImplementedError` (win32com/COM message); `parse_schedule` dispatcher resolves the seam at call
  time (monkeypatchable); contract doc. CI green in 20s; 3 new tests (18 total).

## 3. Milestones in progress
- **M4 — CPM engine:** starting on branch `m4-cpm-engine` off `main`.

## 4. Milestones not started
- M5 — DCMA metrics 1–4.

## 5. STUCK files index
- `STUCK-build-plan-unavailable.md` — reference BUILD-PLAN.md + DCMA source docs not present in the sandbox; proceeding from embedded milestone summaries.
- `STUCK-branch-strategy.md` — harness "develop on `claude/schedule-analysis-tool-UKgXp`" vs experiment "per-milestone branch → main"; resolved in favor of the experiment flow, designated branch kept fast-forwarded to `main`.

## 6. FIDELITY-DECISION files index
_(Logged tradeoffs, ~10 lines each.)_
- `FIDELITY-DECISION-data-model.md` (M2) — sorted-tuples-not-sets (round-trip stability); naive
  datetimes (tz out of scope); calendars-by-FK not nested; strict+frozen+extra-forbid rationale.
- Anticipated (M4/M5): durations/lags as working-time minutes; single-calendar CPM offset axis;
  binary PASS/FAIL severity (WARN not emitted without a cited second threshold).

## 7. FIDELITY-COMPROMISE files index
_(Every deliberate shortcut, however minor. Honesty is the data.)_
- Anticipated: DCMA threshold citations not page-verified against primary sources (Edwards 2016 / RonWinter 2011 / DECM 8.0) because those PDFs/XLSX were unavailable this session. Will be logged when M5 lands.

## 8. Tools / dependencies introduced (rationale)
- **Python 3.13 venv** — M1 target runtime (default `python3` is 3.11; 3.13 at `/usr/bin/python3.13`).
- **Flask 3.1.3** — the web app (M1). **pydantic 2.13.4** — strict frozen data model (M2).
- **pytest 9.0.3** (tests), **ruff 0.15.13** (lint+format), **mypy 2.1.0** (strict types on `app/`) — dev/CI.
- All pip-only and pinned (`requirements.txt` + `requirements-dev.txt`). pip network access confirmed.
- **Workflow facts:** direct push to `main` works; required CI check `check` gates the PR; MCP
  `enable_pr_auto_merge` refuses while checks are pending, so the merge path is: wait for CI success
  (via MCP check-run polling) → `merge_pull_request`. No blocking branch protection beyond the CI check.

## 9. Open questions I would ask if I could
- Are the canonical DCMA thresholds to be sourced from DECM 8.0, the DCMA 14-Point Assessment, or a project-specific override table? (Defaulting to the well-known 14-Point values.)
- Should "missing logic" exempt the project's start/finish milestones by default? (Defaulting to literal count-all; exposing an option.)
- Is the byte-equal round-trip meant to be `model_dump_json` self-stability, or equality against a canonical fixture? (Implementing self-stability.)

## 10. Most useful thing I wrote this session
- _TBD._

## 11. Least useful / most regret
- _TBD._

## 12. Where I would go next
- _TBD as the build progresses._ Immediate next step after the scaffolded milestones:
  real parser adapters behind the M3 seam, MS Project constraint handling + negative float
  in the CPM engine, and DCMA metrics 5–14.
