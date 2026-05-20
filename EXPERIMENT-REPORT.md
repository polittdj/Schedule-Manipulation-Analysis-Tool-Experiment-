# EXPERIMENT REPORT — Schedule Manipulation Analysis Tool (Autonomous M1–M5)

> Rolling final report. The most recently committed version is the experiment's
> output. Updated at least every ~20 min of work and at every PR merge.

## 1. Session start
- **STATUS: M1–M5 ALL COMPLETE & MERGED TO `main`.** 5 PRs (#1–#5), all CI-green, squash-merged.
  40 tests passing; ruff + ruff-format + mypy(strict on `app/`) clean. `main` head: `f35de79`.
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
- **M4 — CPM engine** — PR #4, squash-merged to `main` as **`80d6a3c`**. Working-minute offset axis;
  FS/SS/FF/SF forward+backward passes; total/free slack; critical path; deterministic Kahn topo sort
  (cycle→`CPMError`); calendar math (weekend/holiday skip). CI green in 18s; 10 new tests (28 total).
- **M5 — DCMA metrics 1–4** — PR #5, squash-merged to `main` as **`f35de79`**. Pure functions →
  frozen `MetricResult`; `ThresholdConfig` with cited source; binary PASS/FAIL (no WARN without a
  cited second threshold); `MetricError` on empty denominator. M1 ≤5%, M2 0% leads, M3 ≤5% lags,
  M4 ≥90% FS. CI green in 22s; 12 new tests (40 total).

## 3. Milestones in progress
- _(none — all five milestones merged.)_

## 4. Milestones not started
- _(none — M1–M5 all complete.)_

## 5. STUCK files index
- `STUCK-build-plan-unavailable.md` — reference BUILD-PLAN.md + DCMA source docs not present in the sandbox; proceeding from embedded milestone summaries.
- `STUCK-branch-strategy.md` — harness "develop on `claude/schedule-analysis-tool-UKgXp`" vs experiment "per-milestone branch → main"; resolved in favor of the experiment flow, designated branch kept fast-forwarded to `main`.

## 6. FIDELITY-DECISION files index
_(Logged tradeoffs, ~10 lines each.)_
- `FIDELITY-DECISION-data-model.md` (M2) — sorted-tuples-not-sets (round-trip stability); naive
  datetimes (tz out of scope); calendars-by-FK not nested; strict+frozen+extra-forbid rationale.
- `FIDELITY-DECISION-cpm-engine.md` (M4) — working-minute offset axis; working-time durations/lags;
  single-calendar offset axis; ASAP/no-constraints; tuple-not-list critical_path; free-slack non-clamp.
- `FIDELITY-DECISION-dcma-severity.md` (M5) — DCMA metrics are binary PASS/FAIL; WARN not emitted
  without a cited second threshold; un-runnable metrics raise rather than fabricate; no "ERROR" state.

## 7. FIDELITY-COMPROMISE files index
_(Every deliberate shortcut, however minor. Honesty is the data.)_
- `FIDELITY-COMPROMISE-dcma-citations.md` (M5) — DCMA threshold citations not page-verified against
  primary sources (Edwards 2016 / RonWinter 2011 / DECM 8.0 / NASA-NID) because those PDFs/XLSX were
  unavailable this session. Threshold *values* are canonical; *wording*/page-anchors are unverified.

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
- The **CPM engine on an integer working-minute offset axis** (`app/cpm/engine.py`) plus its
  hand-worked known-answer tests. Choosing offsets (not wall-clock datetimes) as the internal
  axis made the arithmetic exact, killed the end-of-day/start-of-next-day boundary class of bugs
  by construction, and made every value hand-verifiable. Writing the worked examples is also how I
  caught an arithmetic slip in my own plan (Example 1's branch task carries **1** working day of
  slack, not 2) — the test encodes the correct value. This is the load-bearing fidelity component
  and the part most likely to be reused/extended.

## 11. Least useful / most regret
- **`app/cpm/calendar_math.py` is partly speculative.** The CPM core is pure offset arithmetic and
  never calls `add_working_minutes` / `working_minutes_between`; only `minutes_to_working_days` is
  on a real path. I built and tested the wall-clock walk for fidelity/future presentation, but for
  M1–M5 it is infrastructure ahead of a consumer. Also a smaller smell: `Offender.value` is a single
  float overloaded to mean different things per metric (missing-end count / lag minutes / predecessor
  id); a per-metric offender type would be cleaner than documenting the overload.

## 12. Where I would go next
- **Wire it together in Flask:** an upload→`parse_schedule`→`compute_cpm`+metrics→JSON-report route,
  so the 500 MB guard and the analysis core meet. **Harden CPM fidelity:** MS Project constraints
  (SNET/MSO/deadlines), negative float, and multi-calendar lag arithmetic (currently single-calendar).
  **Real parsers** behind the M3 seam (`.xer`/`.xml` first — pure-Python, unlike `.mpp`). **Finish
  DCMA:** metrics 5–14, then manipulation-scoring with the "always-100" regression guard. **Citations:**
  swap the by-name DCMA citations for page-anchored ones once the primary PDFs/XLSX are available.
