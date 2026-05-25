# HANDOFF — Schedule Forensics

> Single "pick up from here" doc for the next person (or future you). Read this,
> then `CLAUDE.md` (the project constitution) and `docs/HAZARDS.md`. Verify any
> rule against the live file before acting on it (do not trust remembered rules).

---

## 0. Status snapshot (2026-05)

- **Branch/state:** `main` is the integration branch; feature work lands via focused
  **squash-merged PRs**. As of this writing `main` is green: **447 pass / 3 skip**,
  `ruff` + `ruff format` + `mypy --strict` clean, 28 source modules, **schema FROZEN
  at v1.2.0**.
- **The tool works and runs locally** end-to-end: ingest → CPM → DCMA-14 +
  driving/critical path + Monte-Carlo SRA + multi-version CEI/trend/diff → Excel/Word
  reports → executive summary → dark localhost UI.
- **ONE open PR:** **#41 "Bundle MPXJ runner"** — *merge this to fix native `.mpp`
  uploads* (see §2.3). Everything else (#27–#40) is merged.
- **Validated against Acumen Fuse** on two real schedules (see §4).

---

## 1. What it is + the two laws

Local-only, CUI-compliant forensic schedule analyzer. Ingests MS Project / Primavera
schedules, runs multi-version comparative analysis, and produces Excel/Word reports
plus a plain-English executive summary. Runs entirely on `127.0.0.1`.

- **LAW 1 — DATA SOVEREIGNTY:** no schedule data leaves the machine; loopback only;
  default classification CUI; fail closed. (Verified: zero network egress in `src/`;
  UI binds `127.0.0.1`; the LLM backends are loopback-enforced.)
- **LAW 2 — FIDELITY OVER SPEED:** numbers must match Acumen Fuse / SSI / MS Project;
  every metric cites a source; tool-original capabilities are labeled extensions;
  no "approximately" (every user-facing number traces to a computed value via a test).
- If they conflict, **Law 1 wins.** Full detail: `CLAUDE.md`.

---

## 2. Run it on YOUR machine (Windows operator path)

### 2.1 Prerequisites
- **Python 3.11+** (https://www.python.org/downloads/ — tick *Add Python to PATH*).
- *(optional, for AI summaries)* **Ollama** — see §2.4.
- *(for native `.mpp`)* a **Java runtime (JRE 17+)** — see §2.3.

### 2.2 Start the tool (PowerShell)
These are **terminal** commands (PowerShell), never the Python `>>>` prompt:
```powershell
cd "C:\path\to\Schedule-Manipulation-Analysis-Tool-Experiment-"   # the repo folder
python -m pip install -e .                # one-time; installs Flask, pydantic, etc.
python -m schedule_forensics.webapp       # serves http://127.0.0.1:5000
```
Open `http://127.0.0.1:5000`. `Ctrl+C` in the window stops it.
**Easier:** double-click `launch\Schedule-Forensics.bat` (or run
`launch\Install-Desktop-Shortcut.bat` once for a desktop icon) — it creates its own
venv, installs, starts/stops Ollama, and opens the browser.

### 2.3 Reading native `.mpp` (the current friction — and the fix)
`.mpp` is a binary format; the tool reads it with **MPXJ** (a Java helper) or, on
Windows, **MS Project COM**. Three options, best first:

1. **MPXJ (recommended; full metadata, no MS Project needed).** Needs only a **Java
   runtime** once **PR #41** is merged — that PR *bundles* the MPXJ jars in the repo
   so there is **no Maven/build step**. Steps: merge #41 → install a JRE 17+
   (Adoptium Temurin, https://adoptium.net, "add to PATH") → re-download the repo →
   `python -m pip install -e .` → upload `.mpp` with the **MPXJ** reader. Verified on
   real `.mpp` files. *(Before #41 is merged, MPXJ requires Java **and** Maven via
   `tools\mpxj\setup.ps1`.)*
2. **MS Project XML (no installs, highest fidelity).** In MS Project: **File → Save
   As → `XML Format (*.xml)`**, then upload the `.xml`. Pure-Python importer; this is
   the exact path validated against Acumen. Select multiple version `.xml` files for
   the comparative view.
3. **MS Project COM (direct `.mpp`, no Java).** `python -m pip install pywin32`, pick
   the **"MS Project"** reader, upload `.mpp`. ⚠️ **Unvalidated** against real MS
   Project — cross-check one file against its XML export before relying on it.

### 2.4 AI-polished executive summary via Ollama (optional, CUI-safe)
Install Ollama → `ollama pull llama3.2`. Then either let the **launcher auto-start/stop
it**, or set it manually: `$env:SF_OLLAMA_MODEL = "llama3.2"` before launching. The
model only *rephrases* the deterministic summary (never changes a number); it runs on
`127.0.0.1` only; if unavailable the summary falls back to the deterministic text. See
`docs/OLLAMA.md`.

---

## 3. Run it for development (Linux/macOS)
```sh
git checkout main && git pull
python3 -m venv .venv && . .venv/bin/activate
pip install -e . && pip install -r requirements-dev.txt
ruff check . && ruff format --check . && mypy && pytest      # expect: ~447 pass / 3 skip
python -m schedule_forensics.webapp          # or: PYTHONPATH=src python -m schedule_forensics.webapp
```
`src/` layout: `pytest` finds the package via `pythonpath=["src"]`; to run the webapp
from a bare checkout without installing, use `PYTHONPATH=src` (or `pip install -e .`).

---

## 4. What's built + Acumen parity status

End-to-end pipeline. Module map (`src/schedule_forensics/`): `schemas.py` (FROZEN
v1.2.0), importers (`msp_xml`, `xer`, `mpp_mpxj`, `com_msproject`), `cpm.py`,
`version_matcher.py`, `dcma_checks.py` + `dcma_progress.py` (all 14 DCMA),
`driving_path.py`, `sra.py` (Monte-Carlo P50/P80/P95 + criticality), `diff_engine.py`
(objective version deltas), `cei.py`, `trend_analysis.py`, `float_analysis.py`,
`performance_indices.py` (SPI/SPI(t)), `analysis.py` (compose), `report_excel.py` /
`report_word.py`, `exec_summary.py`, `inference.py` (LLM backends), `parity.py`
(golden-file harness), `webapp/` (dark UI). Details: `docs/ARCHITECTURE.md`,
`docs/REFERENCES.md` (now cites Acumen's exact DCMA-14 formulas).

**Validated against Deltek Acumen Fuse** (operator supplied real outputs + the metric
library, this session):
- Our DCMA definitions match Acumen's "DCMA 14 Point" group; structural metrics
  matched on real data (Missing Logic, Leads, Lags, Hard Constraints, Negative Float,
  Critical count).
- **#33 fixed a real fidelity bug:** the MSPDI parser silently dropped percent-complete,
  baselines, and resource assignments. That had made DCMA-09/10 *falsely fail* and
  DCMA-11/13/14 *skip*. After the fix all 14 compute and match Acumen's picture
  (severe baseline slip; declining BEI 0.74→0.59, CPLI 0.89→0.68 across two versions).
- **Committed parity fixture** (`tests/fixtures/golden/commercial_construction_p5`):
  CI now asserts **11/11** of our metrics match Acumen's numbers within tolerance.
  Add more real cases via `docs/PARITY.md` (`scripts/parity_report.py`).

---

## 5. Open PR + what's next

- **OPEN — PR #41 (bundle MPXJ):** merge to make native `.mpp` work with only a JRE.
- **Remaining / human-in-loop (need the operator or a Windows box):**
  1. **More real reference cases** — only one Acumen fixture so far; drop in more
     (and SSI / MS Project outputs) to broaden the parity guarantee.
  2. **Windows validation of the COM `.mpp` reader** vs MPXJ/XML on a shared file
     (never run against real MS Project — see `docs/HAZARDS.md` H-NO-COM-HERE).
  3. **Earned value from `.mpp`:** `<Cost>`/budget isn't read yet, so SPI/SPI(t) skip
     on cost-loaded schedules — a natural next parser increment.
  4. **CEI threshold** confirmation (0.95 is source-pending; NDIA prefers a trend).

---

## 6. Conventions & gotchas (read before working)

- **Green bar before every commit:** `ruff check`, `ruff format --check`, `mypy`
  (strict on `src/`), `pytest` — all clean. CI runs the same on Python 3.11 + 3.13.
- **Branch/PR flow:** focused feature branch (recent namespace
  `claude/eager-brown-OYDZw-<topic>`) → **draft PR → `main`**; the operator squash-merges.
  Never push to `main` directly; never force-push a shared branch.
- **Branches are deleted on merge.** Each session, FIRST `git checkout main &&
  git fetch --prune && git reset --hard origin/main` — local feature branches go stale
  and their remotes disappear after squash-merge. (This bit every resume this build.)
- **Parity-honesty:** SRA's *method* is reference parity but its default risk spread is
  a tool heuristic; `diff_engine`/`trend` framing is objective-facts vs tool-extension;
  the self-regression golden case is NOT a parity claim. Keep labeling honest.
- **CUI / LAW 1:** never add a network egress path for schedule data; reports stream
  from memory; real schedule files are never committed (`.gitignore` blocks them;
  `local_parity/` holds real golden cases locally). The reference `.mpp` used this
  session are non-CUI sample files per the operator.
- **Phase reports:** `PHASE-COMPLETE-0/1/2/5/8/9/10.md` capture prior phases.
