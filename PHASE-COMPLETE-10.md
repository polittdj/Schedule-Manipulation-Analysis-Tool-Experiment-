PHASE 10 — Surface the library-only analytics + a checkable parity harness

CONTEXT: Phases 0-9 built the full pipeline (importers -> CPM -> DCMA-14 +
driving-path + SRA + diff/float-trend + CEI + EV indices -> reports -> exec
summary -> localhost UI). An audit of the LIVE code (not the stale HANDOFF) found
three reference-grade modules fully built + tested but reachable only as library
calls -- invisible in the UI and reports -- plus the long-open "make parity
checkable" gap. This phase closes those.

WHAT I BUILT (each: full green bar, real-server smoke test, its own PR):

- SRA in the UI + reports (PR #29, MERGED to main as 2d601bc). run_sra (Monte-
  Carlo finish P50/P80/P95 + per-activity criticality index) now renders as a
  dashboard card and an Excel "Risk (SRA)" sheet + Word section. Computed ONCE on
  the displayed schedule (fixed seed -> UI and reports agree), following the
  trends= precedent (NOT embedded in analyze_schedule, so multi-version uploads
  don't pay the Monte-Carlo cost per version). Auto-SRA is skipped above 300
  activities with a visible note (cost is activities x iterations; 500x2000 ~12s),
  never silently. SRA method = reference parity (Acumen Fuse Risk / Primavera
  Risk); the DEFAULT 0.75/1.5 duration spread = tool heuristic (source-pending),
  captioned as such everywhere (parity-honesty).

- Golden-file parity harness (PR #30, open, CI green). src/schedule_forensics/
  parity.py loads a golden case (input schedule + expected reference values with
  per-check tolerance + cited source), re-runs the analysis, and diffs each value;
  unknown keys / malformed cases fail loud. scripts/parity_report.py is the CLI
  (--root for local CUI cases). tests/fixtures/golden/simple_network_self is a
  SELF-generated regression baseline -- explicitly NOT a parity claim (LAW 2) --
  that guards pipeline drift and exercises the harness in CI. docs/PARITY.md is
  the case format + how to add a real reference-tool case. .gitignore: local_parity/.

- Version-diff in the comparative view + reports (PR #31, open). diff_engine
  (objective consecutive-version deltas: added/deleted, became-critical/recovered,
  finish/float shifts, predecessor add/remove) now renders as a "Version-to-Version
  Changes" card + an Excel "Version Diff" sheet + Word section. Computed via
  diff_consecutive in _store_results (one CPM per version). Measured facts (Acumen
  ProjectTimeNow pattern) -> no threshold, NOT flagged an extension.

WHAT I VERIFIED:
- ruff + ruff-format + mypy (strict, all src) clean on every branch; pytest green
  (main+SRA: 408 pass / 3 skip; +parity: 412; +diff: 415). New tests are
  non-vacuous (perturbed expected -> drift; zero-variance SRA -> exact percentiles;
  a fixture-guard pins the diff scenario).
- LAW 1 held throughout: every addition is pure-local (random + CPM + schemas +
  openpyxl/python-docx + Flask); zero network egress in any diff; the UI still
  binds 127.0.0.1 only; reports stream from BytesIO; parity reads local files only
  and real cases are git-ignored. Real-server smoke tests: SRA card + percentiles +
  caption render and the Risk sheet/section download; the multi-version diff card
  renders alongside Trend + CEI and the Version Diff sheet/section download.
- LAW 2 held: every new user-facing number traces to a computed value via a test;
  SRA method labelled parity while its default spread is labelled a tool heuristic;
  diff deltas labelled objective facts (no threshold); the in-repo parity case is
  labelled a regression baseline, never parity.

WHAT IS STILL OPEN (all HUMAN-IN-LOOP or input-constrained -- I cannot do these):
- Real .mpp validation on Windows / live MS Project COM (no Windows here).
- Real reference-tool numbers for the parity harness (Acumen/SSI/MSP outputs) --
  the harness is ready; only you can supply the expected values.
- CEI real-data threshold confirmation (0.95 source-pending / VERIFY).
- Local Ollama wiring (Phase-7 checkpoint; tool runs fully without it).

LAW 1 CHECK: PASS. No network-egress path touches schedule data; loopback-only UI;
local-only parity; CUI inputs for parity are git-ignored.

LAW 2 CHECK: PASS. New numbers are test-traced and single-source; parity vs tool-
default vs objective-fact are labelled honestly; no "approximately".

REPO STATE: main @ 2d601bc (SRA merged). Open draft PRs: #30 parity (CI green),
#31 version-diff (rebased onto post-#29 main; CI running). Schema FROZEN at v1.2.0
(untouched this phase). 27 source modules. This doc + a HANDOFF refresh land on
the docs branch.

CONFIDENCE: ~85% for a usable local forensic tool over FS/SS/FF/SF networks with
common date constraints. The reference-grade analytics (SRA, version-diff) are now
visible end-to-end, and parity is finally CHECKABLE. Gap to the directive's
"production-ready": real reference-tool parity numbers + live .mpp/MS-Project
validation on Windows -- both require inputs only the operator can provide.

NEXT PHASE: when reference outputs arrive, add real golden cases and triage any
drift; otherwise the human-in-loop checkpoints above.
