# ARCHITECTURE — Schedule Forensics (Phase 1)

Local-only, CUI-compliant forensic schedule-analysis tool. This document is the
self-approved Phase-1 plan. It governs the trust-root spine built in this session
and the phases that follow.

## Tech stack (selections + rejected options)

| Concern | Selected | Rejected (why) |
|---|---|---|
| Language / runtime | **Python 3.11+** (3.11.15 and 3.13.12 both present; target the 3.11 floor) | Pin to 3.13 only (default `python3`/`pip` are 3.11 here → venv friction; offers nothing the spine needs) |
| Data model | **pydantic v2**, `frozen` + `strict` + `extra="forbid"` | dataclasses/attrs (no strict validation / referential-integrity guard); plain dicts (no contract) |
| `.mpp`/`.xml`/`.xer` ingestion | **MSP XML + XER (pure-Python); native `.mpp` via MPXJ-as-subprocess; COM as Windows-only optional** | COM-as-trust-root (untestable off-Windows); **in-process JPype** (top historical build-failure cause — banned, Commandment 1) |
| Web layer | **Flask + Jinja2** on `127.0.0.1` | FastAPI (no concrete advantage for a localhost form-post UI); React SPA (offline build complexity; only if a concrete need arises, and it must build/run fully offline) |
| Reports | **openpyxl** (Excel), **python-docx** (Word) | pandas-to-excel (heavy dep; less cell-level control); LaTeX/PDF (out of scope) |
| Lint / format / types / tests | **ruff**, **mypy --strict** (on `src/`), **pytest** | flake8+black+isort (ruff subsumes); unittest (less ergonomic) |
| Inference (exec summary) | **pluggable backend**: `NullInferenceBackend` default (deterministic), `OllamaBackend` (local), `UnclassifiedClaudeBackend` (network, hard-gated off under CUI) | Hardcoded cloud LLM (violates Law 1); no abstraction (untestable without a model) |

Hard rejections (Law 1): anything requiring cloud hosting, external CDNs at
runtime, a public URL, or telemetry.

## Ingestion fallback chain

```
1. MS Project XML (.xml)    pure-Python, deterministic, no external runtime   [PRIMARY, built]
2. Primavera P6 (.xer)      pure-Python text parser                           [primary, deferred]
3. Native .mpp via MPXJ     subprocess call to a Java/MPXJ CLI (killable);    [primary, deferred]
                            NEVER in-process JPype
4. COM automation (.mpp)    Windows-only optional; behind importer interface; [optional, Windows-only]
                            skip/xfail off-Windows; validated locally
5. Guided XML import        last resort, with explicit lossy-data warnings    [fallback]
   --------------------------------------------------------------------------
   All fail -> a clear remediation error. NEVER silent wrong output.
```

## Data / control-flow (localhost boundary, data-deletion path, inference routing)

```
                         ====================  127.0.0.1 ONLY  ====================
                         |                  (no schedule data ever crosses)        |
  user's browser  --->   |  Flask UI (GET / form)                                  |
  (localhost)            |     |  upload .xml/.xer/.mpp                             |
                         |     v                                                   |
                         |  uploads/  (gitignored runtime dir) --> importer        |
                         |                                          |              |
                         |                                          v              |
                         |                                   Schedule (pydantic,   |
                         |                                   frozen, in-memory)    |
                         |                                          |              |
                         |             +----------------------------+              |
                         |             v              v             v              |
                         |          CPM engine   DCMA / metrics   version_matcher  |
                         |             |              |             |              |
                         |             +------> analysis result <---+              |
                         |                          |                              |
                         |             +------------+-------------+                |
                         |             v                          v                |
                         |     reports (xlsx/docx)        executive summary        |
                         |       exports/ (gitignored)       |                     |
                         |                                    v                     |
                         |                        InferenceBackend (see routing)   |
                         |                                                          |
                         |  [ SESSION-WIPE button ] --> destroys uploads/, parsed  |
                         |     in-memory Schedules, exports/, derived data         |
                         ============================================================
                                              |
                       classification-aware routing boundary (default: CUI)
                                              |
            CUI  -> ONLY NullInferenceBackend or OllamaBackend (local). Network = raise.
       UNCLASSIFIED (explicit opt-in) -> NullInferenceBackend / OllamaBackend /
                                         UnclassifiedClaudeBackend (network, off by default)
```

## Inference-backend abstraction

A single interface (e.g. `summarize(context) -> str`) with implementations:

- **`NullInferenceBackend`** — default. No model. Deterministic, template-based
  placeholder text. Makes the entire tool testable with **zero** model present.
- **`OllamaBackend`** — local Ollama (`127.0.0.1:11434`). CUI-safe. Wired only at
  the Phase-7 human-in-loop checkpoint.
- **`UnclassifiedClaudeBackend`** — network. Usable **only** when classification
  is explicitly `UNCLASSIFIED`. Hard-gated off by default; structurally
  unselectable under any CUI classification.

### Classification × backend routing (single defined behaviour per cell)

| Classification (default = **CUI**) | Null | Ollama (local) | UnclassifiedClaude (network) |
|---|---|---|---|
| **CUI** | allow | allow | **raise** (CUI→network forbidden; covered by a test) |
| **UNCLASSIFIED** (explicit opt-in) | allow | allow | allow (off by default) |

There are no contradictory cases: under CUI, network is always a raise; the
network backend is only constructible/selectable when classification is
explicitly UNCLASSIFIED.

## Phase / milestone plan (maps to the build order)

- **Trust-root spine (sequential):** frozen schema → MSP-XML importer →
  `version_matcher` → CPM engine. **(this session: schema + MSP-XML + minimal CPM
  built and green; matcher + full CPM next.)**
- **Freeze the schema** (version tag + change-control note) before fan-out.
- **Phase 5 fan-out (parallel, worktree-isolated):** `driving_path`,
  `diff_engine` + `float_analysis`, `performance_indices` (SPI/SPI(t)/CEI/BEI),
  `sra` (Monte Carlo BetaPERT), `dcma_checks` (14-point + manipulation, cited).
- **Phase 6 reports:** `report_excel`, `report_word`.
- **Phase 7 executive summary:** inference abstraction; Ollama wiring is the
  human-in-loop checkpoint.
- **Phase 8 UI:** Flask + Jinja2 on `127.0.0.1`, upload + dashboard + session-wipe
  + CUI notice.
- **Phase 9:** integration, regression, hardening, self-improvement loop.

Ingestion expansion (XER, MPXJ-subprocess, optional COM) is parallel-safe work
that slots in after the spine.
