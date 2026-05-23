PHASE 9 (in progress) — Next-work items + hardening rounds

WHAT I BUILT (each verified + committed + pushed; full green bar per push):
- UI port configurable: webapp main() takes --port and reads SF_PORT
  (precedence --port > SF_PORT > default 5000) via a pure, tested resolve_port().
  HOST stays fixed at 127.0.0.1 and is intentionally NOT configurable (LAW 1).
  Invalid/out-of-range values fail closed (raise, never silently bind a default).
- Primavera P6 XER importer (importers/xer.py): pure-Python tab-delimited
  %T/%F/%R/%E parser into the frozen Schedule. UniqueID = TASK.task_id (never
  task_code); duration target_drtn_hr_cnt h x60 -> working min; TASKPRED
  task_id=successor / pred_task_id=predecessor; pred_type PR_FS/SS/FF/SF;
  lag_hr_cnt signed; project_start/last_recalc_date -> start/status. Multi-project
  XER reduced to the majority project; cross-project/dangling links dropped. No
  schema change. Synthetic .xer fixture mirrors the MSPDI fixture; a cross-importer
  test asserts both produce the same network.
- Earned-value indices (performance_indices.py) behind a DELIBERATE schema v1.1.0
  bump (added Task.baseline_start + Task.budgeted_cost; freeze guard updated in the
  same change). SPI = EV/PV (PV time-phased by linear baseline spend); SPI(t) =
  ES/AT (Lipke earned schedule, PV-curve inversion). Both SKIP (never fabricate)
  without status_date / budget / baseline / when PV(status)==0. CEI is
  intentionally NOT implemented -- no single citable definition; deferred
  source-pending per LAW 2 rather than shipping a guessed formula.
- EV wired into ScheduleAnalysis.performance_indices (kept OUT of the DCMA-only
  health_score/findings) and rendered everywhere: Excel "Earned Value" sheet, Word
  "Earned-Value Indices" table, and a dashboard card (SKIPPED note + the 0.95
  "management threshold, not DCMA" caveat).
- Phase-9 hardening (2 rounds, +12 edge-case tests). Round 1 FOUND + FIXED a real
  defect: a duplicate task_id/UID made the XER and MSPDI importers raise a raw
  pydantic ValidationError (and the UI show "Unexpected error") instead of a clean
  ImporterError; both importers now wrap Schedule construction. Plus CRLF, fractional
  hours, short rows, TT_Mile, SPI(t)=BAC cap, milestone budget. Round 2 pinned CPM
  link semantics (FF+lag, FS lead, disconnected components) and a matcher
  status-date tie (stable order) -- no bugs, gaps closed against regression.

WHAT I VERIFIED:
- ruff + ruff-format + mypy(strict, 23 modules) clean; full pytest 306 passed /
  2 skipped; determinism re-confirmed (3 consecutive clean runs each round).
- LAW 1 held throughout: XER/EV are pure-Python, zero network I/O; the UI still
  binds 127.0.0.1 only (port varies, host fixed). Real-server smoke tests:
  --port/SF_PORT bind the chosen port on loopback; the EV dashboard card renders
  with the computed SPI (0.7500) on a live server.
- LAW 2 held: every EV/XER number traces to a computed value via a test; the
  cross-importer test proves XER==MSPDI on equivalent inputs; SPI/SPI(t) thresholds
  are single-source + cited (0.95 labelled a management level, not a DCMA number);
  CEI deferred honestly (named, not faked); XER constraint mapping flagged
  source-pending and the fixture asserts nothing that depends on it.

WHAT IS STILL OPEN:
- MPXJ-as-subprocess for native .mpp (importers/mpp_mpxj.py): needs the MPXJ Java
  toolchain (Maven-reachable here) AND a true binary .mpp fixture -- which cannot
  be created on Linux (MPXJ reads .mpp but does not write it; no MS Project here).
  The .mpp path can therefore only be validated on a Windows box with a real file.
- COM importer (Windows-only; skip/xfail off-Windows) -- a human-in-loop checkpoint.
- Golden-file parity harness vs Acumen Fuse / SSI / MS Project -- needs
  user-supplied reference outputs.
- CEI: define + cite before implementing (would likely need an actual_cost field).
- Local Ollama wiring (Phase-7 human-in-loop checkpoint; the tool runs fully
  without it via NullInferenceBackend).

LAW 1 CHECK: All new code is local-only; no network egress path touches schedule
data; the UI binds loopback only. Offline-safe.

LAW 2 CHECK: Every user-facing number traces to a computed value via a test; new
thresholds single-source + cited; CEI and XER constraint codes are labelled
source-pending rather than presented as parity.

REPO STATE: branch claude/charming-cerf-iddZv; draft PR #24 -> main (do not merge
without permission); schema FROZEN at v1.1.0; 23 source modules; full suite green
(306 passed / 2 skipped). HEAD: the round-2 hardening commit.

CONFIDENCE: 82% for a usable local forensic tool over FS/SS/FF/SF networks with
common date constraints under the default calendar, now with XER ingestion and
earned-value SPI/SPI(t). Gap to the directive's §11 "production-ready": native
.mpp (MPXJ + a Windows-validated .mpp), COM, golden-file parity vs the reference
tools (user inputs), and live MS Project validation on real .mpp (Windows-local).

NEXT PHASE: per user direction at the Phase-9 checkpoint -- MPXJ-subprocess
scaffolding (tested against a hand-authored MPX/XML fixture, .mpp Windows-validated),
or further hardening, or the golden-file parity harness once reference outputs are
supplied.
