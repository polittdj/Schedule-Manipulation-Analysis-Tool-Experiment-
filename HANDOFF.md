# HANDOFF — Schedule Forensics (resume the build)

> **You are a fresh Claude Code session continuing an in-progress build.** Read this
> file first, then `CLAUDE.md` and `docs/HAZARDS.md`. Verify any rule against the
> live file before acting on it (Hazard **H-FICTIONAL-RULE / H13** — do not trust
> remembered rules, including ones in this doc, without checking the live code).

---

## 0. Resume in 60 seconds

```sh
git checkout claude/charming-cerf-iddZv && git pull
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e . && pip install -r requirements-dev.txt
ruff check . && ruff format --check . && mypy && pytest      # expect: all clean, ~363 pass / 3 skip
python -m schedule_forensics.webapp                # serves http://127.0.0.1:5000 (--port / SF_PORT)
```

- **Branch:** `claude/charming-cerf-iddZv` (develop here only; never push elsewhere
  without explicit permission). **Draft PR #24 → main** (do not merge without
  permission). **Schema FROZEN at v1.2.0.** Latest work + open items:
  `PHASE-COMPLETE-9.md`.
- **Green bar before every commit:** `ruff check`, `ruff format --check`,
  `mypy` (strict on `src/`), `pytest` — all clean. CI runs the same on Python
  3.11 + 3.13.
- **Backup of the pre-greenfield build:** tag `pre-greenfield-snapshot-20260522`
  / commit `9edd90f` (recover with `git checkout 9edd90f`).

---

## 1. The two laws (never violate)

- **LAW 1 — DATA SOVEREIGNTY (CUI):** no schedule data leaves the machine; runs on
  `127.0.0.1` only; default classification CUI; fail closed. (Verified: zero
  network imports in `src/`; UI binds loopback; CUI→network inference raises.)
- **LAW 2 — FIDELITY OVER SPEED:** numbers must match Acumen Fuse / Steelray-SSI /
  MS Project; every metric cites a source; tool-original capabilities are labeled
  extensions; no "approximately" (every user-facing number traces to a computed
  value via a test).
- If they conflict, **Law 1 wins.** Full constitution: `CLAUDE.md`.

## 2. Environment reality (this is NOT the directive's Windows/COM world)

Linux container; Python 3.11 + 3.13; Node 22; Java 21. **No Windows, no MS Project
COM, no PowerShell.** By explicit user decision: **primary ingestion is
cross-platform** (MS Project XML + Primavera XER + MPXJ-as-subprocess); **COM is an
optional Windows-only enhancement, never the only path, and never in-process
JPype.** Do not "restore" COM-as-trust-root from the original master directive.

---

## 3. What is built (Phases 0–8 complete, all green)

Pipeline runs end-to-end: **MS Project XML / JSON `Schedule` → CPM → full DCMA-14 +
driving-path + SRA + multi-version diff/float-trend → composition + health score →
Excel/Word reports → executive summary → localhost UI.** Now also: XER ingestion +
earned-value SPI/SPI(t), CEI, and COM ingestion. 26 source modules, ~363 tests. Module map
(`src/schedule_forensics/`):

| Module | Role |
|---|---|
| `schemas.py` | **FROZEN v1.2.0** Pydantic model (`Schedule/Task/Relation/Calendar`); strict, immutable, integrity-guarded; UniqueID-only identity. v1.1.0 added `Task.baseline_start`+`Task.budgeted_cost` (EV); v1.2.0 added `Task.finish` (forecast finish, CEI). `SCHEMA_VERSION` + `tests/test_schema_freeze.py` enforce change-control. |
| `importers/msp_xml.py` | Pure-Python MSPDI (MS Project XML) importer. Dup-UID → `ImporterError`. |
| `importers/xer.py` | Pure-Python Primavera P6 XER importer (`%T/%F/%R/%E`); UniqueID = `task_id`; multi-project → majority project; constraint codes source-pending. |
| `importers/mpp_mpxj.py` | Native `.mpp` via MPXJ **subprocess** (never JPype); `SF_MPXJ_CMD`/`SF_MPXJ_JAR` → MSPDI → `parse_msp_xml`; killable; fail-closed. See `docs/MPXJ.md`. |
| `importers/com_msproject.py` | **Windows-only** MS Project COM importer; pure `schedule_from_com_project` mapping (Linux-tested with a fake), `parse_mpp_via_com` driver (guarded import, headless, ReadOnly). Real-`.mpp` validation is Windows-local. |
| `performance_indices.py` | Earned-value **SPI** (EV/PV) + **SPI(t)** (Lipke earned schedule); SKIP without EV data. Not in the DCMA health score. |
| `cei.py` | **CEI** (Current Execution Index, PASEG 10.4.5): per-period finished/forecast-to-finish count ratio over ≥2 status-dated versions; capped at 1.0; multi-version library fn (like `diff_engine`). |
| `version_matcher.py` | Orders versions by absolute `status_date`; UniqueID-keyed added/deleted/matched. |
| `cpm.py` | CPM forward/backward on an **integer working-minute axis** (480 min = 1 day). All link types FS/SS/FF/SF + lag; SNET/FNET/SNLT/FNLT + deadlines; total/free float incl. negative; critical path = `total_float<=0`. **ALAP/MSO/MFO raise `CPMError` (fail closed)** pending live-MSP validation. `datetime_to_offset` converts dates. |
| `metrics_common.py` | Shared metric contract: `MetricResult`, `Threshold` (single-source, cited), `Direction`, typed `Offender`, `evaluate`/`skipped` (SKIPPED never fabricates). |
| `dcma_checks.py` | DCMA-14 **structural** Metrics 1–8. |
| `dcma_progress.py` | DCMA-14 **progress** Metrics 9–14 (incl. CPLI, BEI, Critical-Path Test). |
| `driving_path.py` | SSI driving-slack trace (relationship free float == 0 ⇒ binding). |
| `sra.py` | Monte-Carlo SRA, BetaPERT 3-point, P50/P80/P95 + criticality index (stdlib `random`, seed-deterministic). |
| `diff_engine.py` | Objective version-pair deltas (duration/float/date shifts, became-critical/recovered, logic add/remove). |
| `float_analysis.py` | Float burn-rate + trend bands — **labeled tool-original extension** (`is_extension=True`). |
| `analysis.py` | `analyze_schedule(schedule) -> ScheduleAnalysis`: composes CPM + all 14 DCMA + driving path + health score (the "always-100" guard). |
| `report_excel.py` / `report_word.py` | openpyxl / python-docx reports over `ScheduleAnalysis`; CUI banner everywhere; round-trip traceability tested. |
| `inference.py` | `Classification` (CUI default), `InferenceBackend` protocol, `select_backend` (**fail closed: non-local backend unselectable under CUI**), `NullInferenceBackend` (default), `OllamaBackend` (local, not wired), `UnclassifiedClaudeBackend` (network, UNCLASSIFIED-only). |
| `exec_summary.py` | `generate_executive_summary` — deterministic factual narrative (GREEN/YELLOW/RED, DCMA %, finish, paths, findings, recommendations); backend only rephrases. |
| `webapp/` | Flask UI on `127.0.0.1`: `/`, `/analyze`, `/wipe`, `/report.{xlsx,docx}`, `/health`; in-memory `_STATE`; no disk writes; CUI banner. Run: `python -m schedule_forensics.webapp`. |

Phase reports with full detail: `PHASE-COMPLETE-0.md`, `-1.md`, `-2.md`, `-5.md`,
`-8.md`. Source/citation manifest: `docs/REFERENCES.md`. Architecture:
`docs/ARCHITECTURE.md`.

---

## 4. Frozen decisions & conventions (do not silently change)

- **Schema is FROZEN at v1.2.0.** Any field add/remove ⇒ bump `SCHEMA_VERSION` AND
  update `tests/test_schema_freeze.py` in the same change (the guard test fails
  otherwise). This is deliberate change-control.
- **UniqueID is the sole cross-version identity key.** Never row `ID`, never name.
- **CPM internal axis = integer working minutes** from `project_start`; wall-clock
  conversion is separate (`offset_to_datetime` / `datetime_to_offset`).
- **Comparative analysis orders by absolute `status_date`** (never relative offsets).
- **Single source of truth per threshold**, each cited; tool-original capabilities
  flagged `is_extension` (currently: `float_analysis` trends, `exec_summary` health
  band). DCMA threshold *values* are canonical but page anchors are **source-pending**.
- **Fail closed, never emit silently-wrong output:** CPM raises on ALAP/MSO/MFO and
  cycles; metrics return SKIPPED (not a fabricated number) when data is missing.

## 5. Next work (prioritized) — pick up here

DONE (this session; see `PHASE-COMPLETE-9.md`):
- ✅ **UI port configurable** — `--port` / `SF_PORT` in `webapp/app.py`; host fixed
  `127.0.0.1`; fail-closed on bad input; tested.
- ✅ **Primavera XER importer** (`importers/xer.py`) — pure-Python, UniqueID =
  `task_id`, preds/lags mapped, cited; synthetic fixture + cross-importer parity.
- ✅ **Earned-value SPI + SPI(t)** (`performance_indices.py`) behind the deliberate
  **schema v1.1.0** bump (`Task.baseline_start` + `Task.budgeted_cost`). Wired into
  `analysis.py` (kept out of the DCMA health score) + Excel/Word/UI + exec summary.
- ✅ **CEI** (Current Execution Index, `cei.py`) behind the deliberate **schema
  v1.2.0** bump (`Task.finish`). Per-period finished/forecast-to-finish count ratio
  (PASEG 10.4.5 / NDIA IPMD); ≥2 status-dated versions (else "insufficient data");
  unmatched task = did-not-finish + diagnostic; capped at 1.0; 0.95 threshold
  source-pending/VERIFY; auto-snapshot = tool-original capture. All importers
  populate `Task.finish`. Multi-version library fn (like `diff_engine`), not in the
  single-schedule UI. 18 tests incl. end-to-end from MSPDI.
- ✅ **Phase-9 hardening rounds 1–3** — fixed the importer error contract (dup
  UID/task_id → `ImporterError`); +17 edge-case tests incl. end-to-end XER≡MSPDI
  full-analysis parity; XER wired into the UI upload; 3 clean runs.
- ✅ **MPXJ-as-subprocess** native `.mpp` (`importers/mpp_mpxj.py`) — out-of-process,
  killable; configured via `SF_MPXJ_CMD`/`SF_MPXJ_JAR`; converts → MSPDI → reuses
  `parse_msp_xml`; **never JPype**. Hermetic stub tests + a live integration test
  (passed against real MPXJ 16.2.0; skips by default). Setup: `docs/MPXJ.md` +
  `tools/mpxj/MpxjToMspdi.java`.

REMAINING (all environment- or input-constrained):
1. ✅ **COM importer** **DONE** (`importers/com_msproject.py`): pure
   `schedule_from_com_project` mapping unit-tested on Linux with a fake COM object;
   `parse_mpp_via_com` is the Windows-only driver (guarded win32com import,
   headless, ReadOnly, defensive teardown). `scripts/validate_against_msp.py` wired
   to it. **Still must be validated against a real `.mpp` on Windows** (enum codes
   + minute units are source-pending, gotcha 10).
2. **Native `.mpp` last mile**: validate the MPXJ path against a REAL binary
   `.mpp` on a machine that has one (cannot be authored on Linux). Optionally wire
   `.mpp` upload into the webapp once MPXJ is a standard server-side dependency.
3. **Golden-file parity harness** (needs the user to supply Acumen/SSI/MSP outputs
   for a known schedule); live-MS Project validation on real `.mpp` (Windows-local).
4. **CEI real-data validation**: confirm the program's CEI threshold (0.95 is the
   common gate but source-pending — NDIA prefers a >75th-percentile trend) and the
   XER `early_end_date`→`finish` mapping against real exports. Consider surfacing
   the multi-version metrics (CEI, `diff_engine`, `float_analysis`) in a comparative
   UI/report view — they are library-only today (the UI is single-schedule).

**HUMAN-IN-LOOP (needs the user, do not attempt to wire alone): local Ollama model
setup** (Phase-7 checkpoint). `OllamaBackend.summarize` is the wiring point and
currently raises. The tool is fully functional without it via `NullInferenceBackend`.
The cloud Claude backend stays hard-gated off under CUI.

## 6. Hard-won lessons (read before dispatching subagents)

- **Trust but VERIFY subagent output.** Subagents have claimed "green" while
  leaving real defects (e.g. report-author: python-docx `Document` factory misused
  as a type; openpyxl sheets typed `object`; stale `# type: ignore`; a test
  assuming openpyxl preserves whole floats — openpyxl round-trips `2.0`→`int 2`).
  After any dispatch: read the code, run the full green bar yourself, and for the
  UI run a real-server smoke test, BEFORE committing.
- **The fan-out ran sequentially** (one `metric-author` at a time into the main
  tree; the gitignored `.venv` makes worktree isolation impractical). Brief each
  subagent precisely (exact APIs, file-ownership, "actually run the green bar"),
  then verify + commit. Each metric module owns its file + test; do NOT let it edit
  `REFERENCES.md` (update citations centrally to avoid conflicts).
- **Don't judge a running agent as stalled by one file's mtime** — it may be
  writing a *different* file. Wait for the completion signal; don't edit its files
  mid-run (a concurrent edit caused a near-collision once).
- **`Edit` with `replace_all` on a trailing comment can merge lines** if mishandled
  — re-run the green bar after bulk edits.
- **mypy + libraries:** python-docx ships `py.typed` (use `docx.document.Document`
  for annotations, `docx.Document()` to construct; `.save()` needs `os.fspath`);
  openpyxl needs the `ignore_missing_imports` override already in `pyproject.toml`.

## 7. Workflow

- Develop on `claude/charming-cerf-iddZv`; commit small, push after each green
  step (so nothing is lost if the container recycles). Draft PR #24 → main; do not
  merge to main without explicit permission; never force-push.
- File-ownership manifest is in `CLAUDE.md` — a subagent writes only files it owns.
- End each phase with a `PHASE-COMPLETE-N.md` (directive §12 format).
- **Standing user instruction (this build):** proceed autonomously — "do what you
  recommend without asking"; the user only wants to be stopped for the two
  human-in-loop checkpoints (Ollama setup; live-COM/MSP) or a genuine blocker.
  Still: commit + push after each step, and beware context exhaustion
  (H-SCOPE-CREEP) — a very long session degrades quality; prefer fresh context for
  large new modules.

## 8. Confidence / honesty

NOT yet "production-ready" per the directive's full §11 (reserve that phrase until
all criteria hold): live-MS Project field validation is Windows-local; golden-file
parity needs user-supplied reference outputs. What exists is a complete, green,
secure, offline local tool over FS/SS/FF/SF networks with common date constraints
under the default calendar — with the gaps above named, not hidden.
