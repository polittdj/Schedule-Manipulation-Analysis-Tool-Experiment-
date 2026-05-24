# HANDOFF — Schedule Forensics (resume the build)

> **You are a fresh Claude Code session continuing an in-progress build.** Read this
> file first, then `CLAUDE.md` and `docs/HAZARDS.md`. Verify any rule against the
> live file before acting on it (Hazard **H-FICTIONAL-RULE / H13** — do not trust
> remembered rules, including ones in this doc, without checking the live code).

---

## 0. Resume in 60 seconds

```sh
git checkout main && git pull                      # feature work merges to main via focused PRs
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e . && pip install -r requirements-dev.txt   # (CI/pytest also work via pythonpath=src)
ruff check . && ruff format --check . && mypy && pytest    # expect: all clean, ~415 pass / 3 skip
python -m schedule_forensics.webapp                # serves http://127.0.0.1:5000 (--port / SF_PORT)
```

- **Branching (this build):** focused feature branches → **draft PR → `main`**;
  the user squash-merges. Recent series used the `claude/eager-brown-OYDZw[-topic]`
  namespace. Never push to `main` directly; never force-push a shared branch.
  **Schema FROZEN at v1.2.0.** Latest work + open items: `PHASE-COMPLETE-10.md`
  (this session); prior: `PHASE-COMPLETE-9.md`.
- **NOTE on `python -m`:** this is a `src/` layout. `pytest` finds the package via
  `pythonpath = ["src"]`; to run the webapp from a bare checkout without
  installing, use `PYTHONPATH=src python -m schedule_forensics.webapp` (or
  `pip install -e .` first).
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

## 3. What is built (Phases 0–10 complete, all green)

Pipeline runs end-to-end: **MS Project XML / XER / native `.mpp` (MPXJ) / JSON
`Schedule` → CPM → full DCMA-14 + driving-path + SRA + multi-version
diff/float-trend/CEI → composition + health score → Excel/Word reports →
executive summary → localhost UI.** The UI takes **`.mpp`/`.xer`/XML uploads
(multi-file for the comparative view)** + an MPXJ/COM reader choice, and surfaces:
single-schedule DCMA + EV (SPI/SPI(t)) + **SRA risk (P50/P80/P95 + criticality)**,
and multi-version **CEI + trend + objective version-diff**. Reports mirror all of
it. ~27 source modules, ~415 tests. Module map (`src/schedule_forensics/`):

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
| `sra.py` | Monte-Carlo SRA, BetaPERT 3-point, P50/P80/P95 + criticality index (stdlib `random`, seed-deterministic). **Surfaced (PR #29):** dashboard card + Excel "Risk (SRA)" sheet + Word section; computed once in the webapp (size-capped, fail-safe), default spread labelled a tool heuristic. |
| `diff_engine.py` | Objective version-pair deltas (duration/float/date shifts, became-critical/recovered, logic add/remove). **Surfaced (PR #31):** comparative "Version-to-Version Changes" card + Excel "Version Diff" sheet + Word section; objective facts, no threshold. |
| `trend_analysis.py` | Multi-version trajectory (finish drift, per-version health) + float-erosion bands — **tool-original extension**. Surfaced in the comparative UI + Excel/Word (PR #28). |
| `parity.py` | Golden-file parity harness (PR #30): load a case (input + expected reference values w/ tolerance + cited source), recompute, diff each value; unknown keys/malformed cases fail loud. CLI `scripts/parity_report.py`; cases under `tests/fixtures/golden/`; see `docs/PARITY.md`. Local-only. |
| `float_analysis.py` | Float burn-rate + trend bands — **labeled tool-original extension** (`is_extension=True`); feeds `trend_analysis`. |
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

DONE in earlier phases (see `PHASE-COMPLETE-9.md` and `-10.md`): UI port config;
XER importer; EV SPI/SPI(t) (schema v1.1.0); CEI (schema v1.2.0); Phase-9 importer
hardening; MPXJ-as-subprocess `.mpp`; COM importer (Linux-mapping-tested);
**`.mpp`/`.mpx`/`.xer`/XML uploads wired into the webapp** (multi-file + MPXJ/COM
reader choice); **CEI + trend surfaced** in the comparative UI + reports.

DONE this session (Phase 10; see `PHASE-COMPLETE-10.md`):
- ✅ **SRA surfaced** (PR #29, merged): Monte-Carlo P50/P80/P95 + criticality index
  in the dashboard + Excel/Word; computed once per analyze (size-capped + fail-safe);
  method = reference parity, default spread = tool heuristic (labelled).
- ✅ **Golden-file parity harness** (PR #30): `parity.py` + `scripts/parity_report.py`
  + `docs/PARITY.md` + a self-regression golden case. Ready for real reference numbers.
- ✅ **Version-diff surfaced** (PR #31): objective `diff_engine` deltas in the
  comparative UI + Excel/Word ("Version-to-Version Changes" / "Version Diff").

REMAINING — all HUMAN-IN-LOOP or input-constrained (cannot be done from Linux/CI alone):
1. **Real reference-tool parity numbers**: the harness (PR #30) is ready; supply
   Acumen Fuse / SSI / MS Project outputs for a known schedule as a golden case
   (`docs/PARITY.md`) and triage any drift. This is the substantive parity claim.
2. **Native `.mpp` + live MS Project validation on Windows**: validate the MPXJ
   path and the COM importer against a REAL binary `.mpp` on a Windows box
   (enum codes + minute units source-pending, gotcha 10). Cannot be authored on Linux.
3. **CEI real-data validation**: confirm the program's CEI threshold (0.95 is the
   common gate but source-pending — NDIA prefers a >75th-percentile trend) and the
   XER `early_end_date`→`finish` mapping against real exports.

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

- Develop on a focused feature branch (recent series: `claude/eager-brown-OYDZw[-topic]`);
  commit small, push after each green step (so nothing is lost if the container
  recycles); open a **draft PR → `main`** per feature. The user squash-merges. Do
  not push to `main` directly; never force-push a shared branch. (When stacking a
  PR on an unmerged one that touches the same files, rebase onto `main` once the
  base merges — see Phase 10's diff PR.)
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
