# EXPERIMENT REPORT — Schedule Manipulation Analysis Tool (Autonomous build: M1–M5 + full DCMA-14)

> Rolling final report. The most recently committed version is the experiment's
> output. Updated at least every ~20 min of work and at every PR merge.

## 1. Session start
- **STATUS: BUILD COMPLETE.** M1–M5 plus the full post-M5 build are merged to `main`. **16 PRs
  (#1–#16)**, every one CI-green and squash-merged. **95 tests passing**; ruff + ruff-format +
  mypy(strict on `app/`, 33 modules) all clean. `POST /analyze` runs the CPM engine (FS/SS/FF/SF +
  lag, MS Project date constraints, deadlines, negative float) + **all 14 DCMA 14-Point metrics** +
  an integrity/health score, and returns per-task timings — end-to-end. `main` head is the commit
  after this report update.
- **What "complete" means here:** the full DCMA-14 forensic analysis tool, callable end-to-end.
  Genuinely out-of-scope / deferred (documented, not silently skipped): real `.mpp`/`.xer` file
  parsing (the M3 seam is a stub — real `.mpp` needs MS Project COM), progress/data-date CPM
  rescheduling (one Metric 9 sub-check rides on it), ALAP scheduling (raises), and a deeper
  manipulation-detection model beyond the DCMA-based health score.
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

## 3. Beyond-M5 work (all merged)
- **Post-M5 integration (PR #6, `e400dfc`)** — `analyze_schedule` + `POST /analyze` compose
  M1+M2+M4+M5 end-to-end (JSON `Schedule` in → CPM + DCMA metrics report out; 400/422 error paths;
  un-runnable metrics recorded as skipped, never faked). Composition only, no new fidelity claims;
  6 integration tests. Demonstrates the milestones form a working product.
- **Post-M5 DCMA metrics 6 & 7 (PR #7, `c15790c`)** — High Duration (>44 working days) and High
  Float (CPM total float >44 working days), both `<= 5%`, reusing the model + CPM output (no new
  model fields). Wired into `/analyze`; 6 known-answer tests. Coverage rationale for the deferred
  metrics in `FIDELITY-DECISION-dcma-coverage.md`.
- **Post-M5 deadlines + DCMA Metric 8 (PR #8, `0742d28`)** — `Task.deadline` (MSP-faithful: caps the
  late finish, never reschedules) → negative total float in the CPM backward pass; critical path
  refined to `total_slack <= 0`; Metric 8 (Negative Float, threshold 0%) wired into `/analyze`.
  Finally gives `working_minutes_between` a real consumer. 5 new tests (57 total).
- **Post-M5 per-task timings (PR #9, `925e3cd`)** — the `/analyze` report now exposes per-task
  ES/EF/LS/LF + total/free slack (minutes), total slack in working days, and an `is_critical` flag —
  a forensic report should surface the computed schedule, not just the critical path. 58 tests total.
- **Post-M5 CPM date constraints (PR #10, `1a76008`)** — `ConstraintType` (SNET/SNLT/FNET/FNLT/MSO/
  MFO + ASAP/ALAP) on `Task`; CPM honors them under MSP's "honor constraint dates" mode (floor early /
  cap late / pin hard), surfacing conflicts as negative float; ALAP raises rather than mis-schedule.
  Hand-computed known-answer tests (SNET float, MSO/FNLT negative float). 65 tests total.
- **Post-M5 DCMA Metric 5 (PR #11, `dbe3ad1`)** — Hard Constraints (MSO/MFO/SNLT/FNLT), `<= 5%`,
  wired into `/analyze`. **Completes DCMA Metrics 1–8.** 68 tests total.
- **Metric-numbering fix (PR #12, `6373355`)** — caught + corrected a fidelity error: my float/
  duration metric IDs were permuted vs canonical DCMA (High Float=6, Negative Float=7, High
  Duration=8). Logic unchanged; labels corrected. 68 tests.
- **Tracking-data model (PR #13, `1152648`)** — `Task` gains percent_complete / actual_start /
  actual_finish / baseline_finish / resource_names; `Schedule` gains status_date + project
  baseline_finish; `MetricResult.measured` for index metrics. Foundation for 9–14. 73 tests.
- **DCMA Metrics 9/10/11 (PR #14, `bc98186`)** — Invalid Dates (0%), Resources (≤5%), Missed Tasks
  (≤5%); raise (→ report-skipped) when their tracking data is absent. 82 tests.
- **DCMA Metrics 12/13/14 (PR #15, `d7976c4`)** — Critical Path Test (re-runs CPM with an injected
  delay), CPLI (index via `measured`, ≥0.95), BEI (≥95%). **Completes all 14 DCMA metrics**; an
  end-to-end test runs all 14 on a fully-tracked schedule. 91 tests.
- **Integrity/health score (PR #16, `6c2cb32`)** — `assess_health` aggregates the metrics into a
  pass-rate score + findings list, in the `/analyze` report; carries the **"always-100" regression
  guard** (score derived from the real pass count, so any failing metric pulls it below 100). 95 tests.

## 4. Milestones not started
- _(none — M1–M5 complete; the DCMA-14 build is complete.)_

## 5. STUCK files index
- `STUCK-build-plan-unavailable.md` — reference BUILD-PLAN.md + DCMA source docs not present in the sandbox; proceeding from embedded milestone summaries.
- `STUCK-branch-strategy.md` — harness "develop on `claude/schedule-analysis-tool-UKgXp`" vs experiment "per-milestone branch → main"; resolved in favor of the experiment flow, designated branch kept fast-forwarded to `main`.

## 6. FIDELITY-DECISION files index
_(Logged tradeoffs, ~10 lines each.)_
- `FIDELITY-DECISION-data-model.md` (M2) — sorted-tuples-not-sets (round-trip stability); naive
  datetimes (tz out of scope); calendars-by-FK not nested; strict+frozen+extra-forbid rationale.
- `FIDELITY-DECISION-cpm-engine.md` (M4, updated post-M5) — working-minute offset axis; working-time
  durations/lags; single-calendar offset axis; ASAP + **date constraints (SNET/FNET/SNLT/FNLT/MSO/
  MFO)** and **deadlines** honored ("honor constraint dates" mode) → negative float; **critical path
  `total_slack <= 0`**; **ALAP raises** (not mis-scheduled); tuple-not-list critical_path; free-slack non-clamp.
- `FIDELITY-DECISION-dcma-severity.md` (M5) — DCMA metrics are binary PASS/FAIL; WARN not emitted
  without a cited second threshold; un-runnable metrics raise rather than fabricate; no "ERROR" state.
- `FIDELITY-DECISION-dcma-coverage.md` (updated) — **all 14 DCMA metrics implemented**; documents the
  simplifications: no progress/data-date rescheduling (so Metric 9's forecast sub-check is omitted and
  forecasts ignore actuals), the Metric 10 threshold reading, and the ALAP rejection.

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
- Should "missing logic" (Metric 1) exempt the project's start/finish milestones by default? (Defaulting to literal count-all; exposing `exclude_project_bookends`.) This is why most small schedules score < 100 on the health metric.
- What is the intended Metric 10 (Resources) threshold and population — all detail tasks, incomplete tasks only, cost-or-resource? (Implemented: ≤5% of duration>0 tasks missing a resource.)
- Was a manipulation-*scoring* algorithm part of the canonical tool (the prompt's "always-100 bug" hint), and if so what's its methodology? (Implemented a transparent DCMA-pass-rate health score with the always-100 guard; a real manipulation model would need its own spec.)
- Should the CPM do data-date/progress scheduling? (Currently forecasts from project start; see §11.)

## 10. Most useful thing I wrote this session
- The **CPM engine on an integer working-minute offset axis** (`app/cpm/engine.py`) plus its
  hand-worked known-answer tests. Choosing offsets (not wall-clock datetimes) as the internal
  axis made the arithmetic exact, killed the end-of-day/start-of-next-day boundary class of bugs
  by construction, and made every value hand-verifiable. Writing the worked examples is also how I
  caught an arithmetic slip in my own plan (Example 1's branch task carries **1** working day of
  slack, not 2) — the test encodes the correct value. This is the load-bearing fidelity component:
  date constraints, deadlines, negative float, CPLI's forecast, and the critical-path test all
  built cleanly on top of the offset axis without reworking it — the clearest payoff of the session.

## 11. Least useful / most regret
- **`Offender.value` is an overloaded float** — it means a different thing per metric (missing-end
  count / lag minutes / predecessor id / working days / a 1.0 flag). It's documented per metric, but a
  small per-metric offender type (or a typed `kind` + payload) would be cleaner and less error-prone.
  This is the clearest piece of accumulated design debt.
- **Most regret — no progress/data-date scheduling.** The CPM forecasts every task from
  `project_start` ignoring recorded actuals, so a mid-execution schedule isn't rescheduled from the
  data date. The progress metrics (9/11/13/14) read the tracking fields correctly, but Metric 9's
  "forecast remaining work before the data date" sub-check is omitted and CPLI's forecast is the
  pure-logic finish. It's honestly documented, but it's the one place the fidelity is genuinely
  reduced rather than just bounded. (Upside resolved along the way: `add_working_minutes` —
  earlier flagged as test-only — is now a real consumer via CPLI's forecast-date conversion.)
- **Process slip (caught + recovered):** in PR #8 I committed the deadline work onto local `main`
  instead of branching first; caught it before pushing (`origin/main` never advanced), reset local
  `main`, and re-routed through the PR. No history damage, but an honest lapse in branch discipline.

## 12. Where I would go next
The DCMA-14 build is complete. The remaining work is genuine new scope, not unfinished business:
- **Progress / data-date (status) scheduling** in the CPM engine — reschedule remaining work from
  the data date and consume actuals/percent-complete for remaining duration. This is the biggest
  fidelity upgrade: it closes Metric 9's omitted forecast sub-check and makes CPLI's forecast
  status-aware. (See §11.)
- **Real parsers** behind the M3 seam — `.xer`/`.xml` (Primavera) first, since they're pure-text
  (unlike `.mpp`, which needs MS Project COM). A real parser would also exercise the full wall-clock
  calendar walk on ingest.
- **ALAP scheduling** (currently raises) — needs a backward-driven pass.
- **Deeper manipulation detection** beyond the DCMA-based health score (e.g. version-to-version
  diffing on UniqueID to spot date/logic manipulation between updates).
- **Citations:** swap the by-name DCMA citations for page-anchored ones once the primary
  PDFs/XLSX are available; revisit the Metric 10 threshold against a primary source.
