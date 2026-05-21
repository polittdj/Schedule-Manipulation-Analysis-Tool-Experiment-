# Schedule Manipulation Analysis Tool (Experiment)

A forensic schedule-analysis tool. It ingests project schedules (MS Project / Primavera)
and runs DCMA-14 schedule-quality metrics and critical-path (CPM) analysis. This repository
is an **autonomous build experiment** — see [`EXPERIMENT-REPORT.md`](EXPERIMENT-REPORT.md).

> Fidelity-first: results aim to match Acumen Fuse / Steelray / MS Project semantics.
> Speed and elegance are tiebreakers, never overrides.

## Get a ready-to-run app (no Python at all)
The easiest option — a single self-contained program, nothing to install:
1. On GitHub, open the **Actions** tab → **Build apps** → **Run workflow** (or push a tag like `v0.1.0`).
2. When it finishes, open that run and download the artifact for your system from **Artifacts**:
   `ScheduleTool-windows`, `ScheduleTool-macos`, or `ScheduleTool-linux`.
3. Unzip it and **double-click `ScheduleTool`** (`ScheduleTool.exe` on Windows). Your browser opens
   to the tool. A small console window stays open — close it to stop the tool.
   - First open on macOS may be blocked: right-click → **Open** → **Open**. (The app is unsigned.)
   - The CI-built app **bundles a Java runtime**, so native `.mpp` import works with nothing else to
     install.

Prefer to build it yourself? Double-click **`build-app.command`** (macOS/Linux) or
**`build-app.bat`** (Windows) — it produces the same program in the `dist/` folder. (Building needs
Python 3.13 once; *running* the result does not. PyInstaller can't cross-build, so build on the OS
you want the app for.) If a JDK (with `jlink`) is on your machine at build time, the script bundles a
JRE so the built app reads `.mpp` too; otherwise it still builds, just without native `.mpp`.

## Quick start — click to run (no terminal)
You need **Python 3.13** installed once (from python.org). Then:
1. Download this project (green **Code** button → **Download ZIP**, then unzip — or `git clone`).
2. Double-click the launcher in the project folder:
   - **macOS / Linux:** `Start-Schedule-Tool.command`
   - **Windows:** `Start-Schedule-Tool.bat`
3. The first run installs everything automatically (about a minute). Then your browser opens to
   the tool. Paste a schedule (or click **Load example**) and press **Analyze schedule**.
4. To stop it, close the little window the launcher opened.

**Make it a desktop icon:**
- **Windows:** right-click `Start-Schedule-Tool.bat` → **Send to → Desktop (create shortcut)**.
  (Right-click the shortcut → Properties → Change Icon to pick a picture.)
- **macOS:** drag `Start-Schedule-Tool.command` to the Desktop while holding **⌘+⌥** (makes an alias).
  If macOS blocks it the first time, right-click → **Open** → **Open**.
- **Linux:** right-click `Start-Schedule-Tool.command` → mark as executable, then copy it (or a
  `.desktop` shortcut) to your Desktop.

## Loading real files
The web UI's **Import** button reads:
- **MS Project XML** (`.xml`, *File → Save As → XML*) and **Primavera P6** (`.xer`) — pure-Python, no setup.
- **Native MS Project `.mpp`** — via **MPXJ** (optional): needs Java 17+ and `pip install -r requirements-mpp.txt`
  (the launcher installs it automatically when possible). The CI-built standalone app bundles its own
  JRE, so `.mpp` works there with no setup. Without Java/MPXJ, use *Save As → XML*.

Importers are **best-effort** (validated against crafted samples; the `.mpp`/MPXJ path is the most
mature) — eyeball an imported schedule before relying on it. See `FIDELITY-COMPROMISE-importers.md`
and `docs/skills/native-mpp-parser.md`.

## Status
- **M1 — Scaffolding:** Flask app factory, 500 MB upload guard + 413 handler, CI.
- **M2 — Data model:** strict/frozen Pydantic `Schedule`/`Task`/`Relation`/`Calendar` (+ constraints, deadlines, baseline/actual tracking data).
- **M3 — Parser seam:** native import — MS Project `.xml` & `.mpp` (MPXJ) and Primavera `.xer`.
- **M4 — CPM engine:** FS/SS/FF/SF + lag, MS Project date constraints, deadlines, total/free slack, negative float, critical path.
- **M5+ — DCMA metrics:** **all 14** of the DCMA 14-Point assessment, plus an integrity/health score.

See [`docs/dcma-metrics.md`](docs/dcma-metrics.md) and [`docs/cpm-model.md`](docs/cpm-model.md).

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

## Running (for developers)
```sh
python launch.py                          # starts the server AND opens the browser UI at /
# or:
flask --app "app:create_app" run          # http://localhost:5000/  (browser UI), /health, /analyze
```
- `GET /` — the browser UI (paste a schedule, click Analyze).
- `POST /analyze` — validates a JSON `Schedule`, runs the CPM engine and all 14 DCMA metrics, and
  returns per-task timings (ES/EF/LS/LF/slack), the critical path, project finish (working days),
  per-metric results, and an integrity/health score (share of runnable metrics that pass, with the
  failing metrics listed as findings). Example:
  ```sh
  curl -X POST http://localhost:5000/analyze \
    -H 'Content-Type: application/json' --data-binary @schedule.json
  ```

## Security note
Schedule files (`*.mpp`, `*.xer`, `*.xml`) may carry Controlled Unclassified Information
and are git-ignored. Do not commit them.
