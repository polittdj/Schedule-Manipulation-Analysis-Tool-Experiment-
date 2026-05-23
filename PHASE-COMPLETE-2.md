PHASE 2 COMPLETE — Trust-Root Spine Complete + Schema FROZEN

WHAT I BUILT (incrementally, each commit green + pushed):
- version_matcher.py — orders schedule versions by absolute status_date
  (ProjectTimeNow pattern); matches tasks across versions by UniqueID only;
  reports matched/added/deleted per consecutive version pair.
- CPM engine completed to all four link types (FS/SS/FF/SF) with lag/lead, in
  exact working-minute offsets; free float generalized via per-link relationship
  slack (total float exact for every type).
- CPM date constraints honored under MS Project "honor constraint dates" mode:
  SNET/FNET (forward floors), SNLT/FNLT + task deadlines (backward caps that drive
  negative float, propagated along the driving chain). datetime_to_offset converts
  constraint datetimes (working-day granularity + clamped intraday).
- Schema FROZEN at SCHEMA_VERSION 1.0.0 with a field-set guard test
  (test_schema_freeze.py) enforcing change-control (H-DRIFT-2).

WHAT I VERIFIED:
- ruff + ruff-format + mypy(strict, src/) clean; full pytest suite green and
  deterministic. CI green on the matrix (Python 3.11 + 3.13) per push.
- Every CPM number is hand-computed in tests, including negative-float cases
  (FNLT/SNLT/deadline violations) and a perturbation that flips the verdict
  (H-VACUOUS-TEST). datetime_to_offset tested for day-count, weekend-skip, and
  intraday-clamp.
- The schema survived the importer + matcher + full CPM with zero field changes —
  the evidence that justified freezing it.

WHAT IS STILL OPEN (named, not silently skipped):
- CPM: ALAP / MSO / MFO are FAIL-CLOSED (raise CPMError) pending live-MS Project
  validation (H-CONSTRAINT-DATETIME); progress / data-date (status) scheduling.
- Importers: Primavera XER, native .mpp via MPXJ-subprocess, optional Windows COM.
- MSPDI <LinkLag> unit and intraday/non-working-day constraint mapping are
  SOURCE-PENDING (documented; fixtures avoid depending on them).
- Phase-5 analysis fan-out (DCMA-14 + manipulation, driving-path, diff/float,
  SPI/CEI/BEI, SRA), reports, executive summary, UI.

LAW 1 CHECK: No network egress; engine + importer are pure local computation; only
synthetic fixtures tracked. Offline-safe.

LAW 2 CHECK: Constraints honored per documented "honor constraint dates" semantics;
unvalidatable pin constraints fail closed rather than emit wrong numbers. Modeling
choices flagged source-pending in docs/HAZARDS.md; no unearned parity claimed.

REPO STATE: branch claude/charming-cerf-iddZv; draft PR #24 -> main; CI green.

RECOVERY POINT: Spine is on the branch. Re-establish the green bar with
`pip install -r requirements-dev.txt` then
`ruff check . && ruff format --check . && mypy && pytest`.

CONFIDENCE: 80% the spine is forensically sound for FS/SS/FF/SF networks with the
common date constraints under the default calendar. Remaining gap to a real
forensic tool: ALAP/MSO/MFO, progress scheduling, broader ingestion, the analysis
fan-out, and validation against live MS Project on real .mpp (Windows-local).

NEXT PHASE: Phase-5 analysis fan-out on the frozen schema — start with DCMA-14 +
manipulation checks (cited) and the diff/float-trend module, dispatched as
worktree-isolated subagents with the read-only auditors as merge gates.
