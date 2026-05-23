PHASE 0 COMPLETE — Constitution, Crew & Safe Greenfield

WHAT I BUILT:
- Safe greenfield reset of branch `claude/charming-cerf-iddZv`, HISTORY-PRESERVING:
  the prior 37-commit build's tree was removed via `git rm -r` and the greenfield
  skeleton committed ON TOP (the old commits remain reachable; a normal non-force
  push preserves everything).
- Safety net BEFORE any destruction: local backup branch
  `backup/pre-greenfield-20260522-161223` and tag `pre-greenfield-snapshot-20260522`
  at the pre-wipe HEAD `9edd90f`. (Remote tag push is blocked by the git proxy with
  HTTP 403 — only the designated branch is pushable — but `origin/claude/charming-
  cerf-iddZv` still points at `9edd90f`, so the pre-greenfield state is recoverable
  remotely as well.)
- Constitution + crew: `CLAUDE.md` (two laws, adapted 10 commandments, citation +
  parity-honesty rules, file-ownership manifest, Windows/COM gotchas, parallelism
  model), 10 specialist subagents in `.claude/agents/`, `.claude/settings.json`
  (read-only allowlist).
- Skeleton: `.gitignore` (blocks all schedule formats; synthetic-fixture exception),
  `pyproject.toml` (pinned deps + ruff + pytest + mypy-strict), `requirements*.txt`,
  `README.md`, `docs/REFERENCES.md`, `docs/HAZARDS.md`, `docs/ARCHITECTURE.md`,
  `src/schedule_forensics/` package, `tests/` + `tests/fixtures/`,
  `scripts/validate_against_msp.py` (Windows/COM stub).

ENVIRONMENT VALIDATION (adapted §3.5 — Linux):
- python3 3.11.15 AND python3.13 3.13.12 present; pip 24.0 (on 3.11); node v22.22.2;
  java OpenJDK 21.0.10; git 2.43.0.
- `win32com` import: ModuleNotFoundError — Windows COM is unavailable here (expected).
  Recorded as Windows-only/deferred (H-NO-COM-HERE). PowerShell absent. Targeting
  Python 3.11+ so the green bar runs with the default interpreter.

WHAT I VERIFIED:
- `.gitignore` blocks `*.mpp/*.xer/*.xml/*.csv` and runtime data dirs, while the
  synthetic fixture `tests/fixtures/msp_xml/simple_network.xml` remains trackable
  (confirmed: it is staged for addition).
- Backup refs exist; remote branch retains full pre-wipe history at `9edd90f`.

WHAT IS STILL OPEN:
- All ingestion beyond MS Project XML (XER, MPXJ-subprocess, optional Windows COM).
- The analysis fan-out, reports, inference/exec-summary, and UI (later phases).

LAW 1 CHECK: No network egress introduced. All schedule formats gitignored; only
synthetic fixtures tracked. Self-reviewed; `security-cui-auditor` not yet invoked
(its definition is now in place for later gate use).

LAW 2 CHECK: Fidelity scaffolding in place (REFERENCES manifest, citation +
parity-honesty rules, single-source-of-truth thresholds policy). No metrics ship in
Phase 0, so no parity claims made.

REPO STATE: branch `claude/charming-cerf-iddZv`; greenfield commit pushed; draft PR
to `main` opened for review visibility. CI: repo-local checks (ruff/mypy/pytest) green.

RECOVERY POINT: Work is the greenfield commit on `claude/charming-cerf-iddZv`. To
recover the prior build: `git checkout 9edd90f` (or the backup branch/tag). To resume:
continue the trust-root spine (version_matcher + full CPM), then freeze the schema.

CONFIDENCE: 80% that the foundation (constitution, safety, skeleton) is sound for a
forensic build. The −20% is real-`.mpp`/COM validation, which is inherently
Windows-local and cannot be exercised in this Linux session.

NEXT PHASE: Phase 1 architecture is already documented and the trust-root slice is
built (see PHASE-COMPLETE-1.md). Next: `version_matcher` + full CPM (SS/FF/SF +
constraints), then FREEZE the schema before the analysis fan-out.
