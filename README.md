# Schedule Forensics

A **local-only, CUI-compliant** forensic schedule-analysis tool. It ingests
project schedules (MS Project / Primavera), runs critical-path (CPM) analysis and
schedule-quality/forensic metrics (DCMA-14, SPI/CEI/BEI, SRA, manipulation
detection), and produces Excel/Word reports plus a plain-English executive
summary. It runs entirely on `127.0.0.1` — **no schedule data ever leaves the
machine** (see `CLAUDE.md`, Law 1).

> Fidelity-first: results aim to match Deltek Acumen Fuse / Steelray-SSI /
> Microsoft Project semantics. Speed and elegance are tiebreakers, never
> overrides (Law 2).

## Status

A complete, offline forensic analysis engine runs end-to-end (MS Project XML or a
JSON `Schedule` → CPM → full DCMA-14 + driving-path + SRA + multi-version
diff/float-trend → Excel/Word reports + a plain-English executive summary), with a
localhost web UI. **Built and green:**

- **Frozen data model** (`schemas.py`, v1.0.0): strict, immutable,
  referential-integrity guarded; cross-version identity by `UniqueID` only.
- **Ingestion**: MS Project XML importer (pure-Python). XER / native `.mpp`
  (MPXJ-subprocess) / optional Windows-only COM are **deferred**.
- **CPM engine** (`cpm.py`): forward/backward pass on an integer working-minute
  axis; all four link types (FS/SS/FF/SF) + lag; SNET/FNET/SNLT/FNLT + deadlines;
  total/free float (incl. negative); critical path. ALAP/MSO/MFO **fail closed**
  (raise) pending live-MS Project validation.
- **Version matcher**, **DCMA 14-Point** (all 14), **driving path** (SSI slack),
  **SRA** (Monte-Carlo BetaPERT), **diff/float-trend** (manipulation analysis),
  an **analysis composition layer** + integrity score, **Excel/Word reports**, and
  a **pluggable executive summary** (NullInferenceBackend default; CUI-gated).
- **Localhost UI** (`webapp/`): Flask on `127.0.0.1`, upload → dashboard → report
  download, session-wipe, CUI banner.

**Deferred / next:** Primavera XER + MPXJ-subprocess + COM ingestion; cost-based
SPI/CEI earned-value indices (a deliberate schema v1.1.0 bump); the local Ollama
model wiring (a human-in-loop step); validation against live MS Project on real
`.mpp` (Windows-local).

## Run the tool (localhost UI)

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m schedule_forensics.webapp   # serves http://127.0.0.1:5000
```

Open `http://127.0.0.1:5000`, paste a JSON `Schedule` (or upload MS Project XML),
and click Analyze. Use **Wipe** to destroy all in-memory data. Nothing leaves the
machine (Law 1).

## Develop

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && mypy && pytest
```

Both Python 3.11 and 3.13 work; the project targets **3.11+**.

## Layout

- `src/schedule_forensics/` — the package (schema, importers, CPM engine).
- `tests/` — pytest suite; `tests/fixtures/` holds **synthetic** schedules only.
- `docs/` — `ARCHITECTURE.md`, `REFERENCES.md` (source manifest), `HAZARDS.md`.
- `scripts/` — local validation harness (`validate_against_msp.py`, Windows/COM).
- `CLAUDE.md` — the project constitution (the two laws, commandments, hazards,
  file-ownership manifest). Read it before contributing.

## Platform note

The primary ingestion path (MS Project XML + Primavera XER + native `.mpp` via
MPXJ-as-subprocess) is cross-platform. COM automation is an **optional
Windows-only** enhancement, validated locally; it is never the only path.

## Security note (CUI)

Schedule files (`*.mpp`, `*.xer`, `*.xml`, `*.mpx`, `*.csv`) may carry Controlled
Unclassified Information and are git-ignored. Do not commit real schedule data.
Only synthetic fixtures under `tests/fixtures/` are tracked.
