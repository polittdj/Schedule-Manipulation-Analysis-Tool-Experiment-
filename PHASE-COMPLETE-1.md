PHASE 1 COMPLETE — Architecture + Trust-Root Spine Slice

WHAT I BUILT:
- `docs/ARCHITECTURE.md`: tech stack with rejected options, the ingestion fallback
  chain (XML/XER/MPXJ-subprocess primary; COM Windows-only optional; in-process
  JPype banned), an ASCII data/control-flow diagram showing the upload location, the
  127.0.0.1 boundary, the session-wipe/data-deletion path, and the
  classification-aware inference-routing boundary; the inference-backend abstraction
  (Null/Ollama/UnclassifiedClaude) with a single-defined-behaviour (classification ×
  backend) routing table; and the phase plan.
- A vertical slice through the trust-root spine (the smallest thing that fails the
  way the product fails — a wrong number):
  * `src/schedule_forensics/schemas.py` — FROZEN-CANDIDATE Pydantic model
    (`Schedule`/`Task`/`Relation`/`Calendar`): strict + frozen + extra-forbid;
    referential integrity enforced so an invalid schedule is unconstructable;
    cross-version identity by `unique_id` only; status/constraint/tracking fields
    declared up front so the freeze stays durable.
  * `src/schedule_forensics/importers/msp_xml.py` — pure-Python MSPDI importer
    (namespace-stripping; ISO-8601 duration → working minutes; ConstraintType/link
    enum-code maps; null/sentinel handling; zero network I/O).
  * `src/schedule_forensics/cpm.py` — CPM forward/backward pass on an integer
    working-minute axis; Finish-to-Start with lag/lead; total + free float; negative
    float under an imposed `required_finish_offset`; critical path = total_float ≤ 0;
    Kahn topo sort (cycle → CPMError); calendar offset → wall-clock helper.

WHAT I VERIFIED:
- `ruff check` clean; `ruff format --check` clean; `mypy` (strict, 5 source files) —
  no issues; `pytest` — 25 passed, deterministic across 3 consecutive runs.
- End-to-end fidelity gate (`test_end_to_end.py`): MSPDI fixture → Schedule → CPM
  reproduces independently HAND-COMPUTED early/late/float values, the critical path
  (1,2,4), the project finish offset (2400 min), and the wall-clock finish
  (Fri 2025-01-10 16:00, correctly skipping no weekend over 5 working days).
- Non-vacuous suite (H-VACUOUS-TEST): perturbation tests fail when inputs change
  (`test_perturbation_flips_criticality`, `test_duration_mutation_is_actually_read`),
  and every "invalid construction" schema test asserts a raise.

WHAT IS STILL OPEN (named, not silently skipped):
- CPM: SS/FF/SF link types, the full date-constraint matrix (SNET/SNLT/FNET/FNLT/
  MSO/MFO) + deadlines, calendar-aware negative float, progress/data-date scheduling.
- `version_matcher` (UniqueID-keyed, absolute-StatusDate ordering) — next on the spine.
- Importers: Primavera XER, native `.mpp` via MPXJ-subprocess, optional Windows COM.
- MSPDI `<LinkLag>` unit and calendar-day-encoded durations are SOURCE-PENDING
  (H-MSPDI-LAG-UNIT / H-MSPDI-DURATION-DAYS); golden fixtures avoid depending on them.
- Analysis fan-out (DCMA-14 + manipulation, driving-path, diff/float, SPI/CEI/BEI,
  SRA), reports, executive summary, and UI.

LAW 1 CHECK: The slice performs zero network I/O (pure-Python XML parse + arithmetic).
No schedule data is committed; only the synthetic fixture is tracked. Offline-safe.

LAW 2 CHECK: Every asserted number is independently hand-computed (never read back
from the engine). No "approximately". Foundational semantics (UniqueID identity,
absolute-status-date ordering, critical path = TF ≤ 0, working-minute axis, MSPDI
enum codes) are cited in `docs/REFERENCES.md`; the lag-unit assumption is flagged
source-pending rather than claimed as parity.

REPO STATE: branch `claude/charming-cerf-iddZv`; greenfield + slice committed and
pushed; draft PR → `main`. Repo-local green bar passing.

RECOVERY POINT: The spine slice is on `claude/charming-cerf-iddZv`. Re-establish the
green bar with `pip install -r requirements-dev.txt` then
`ruff check . && ruff format --check . && mypy && pytest`.

CONFIDENCE: 78% that the spine is forensically sound as far as it goes (FS networks,
default calendar). The gap to a real forensic tool is the deferred breadth above —
especially SS/FF/SF + constraints, version comparison, and validation against live
MS Project on real `.mpp` files (Windows-local).

NEXT PHASE: build `version_matcher`, then complete the CPM (all link types +
constraints/deadlines + calendar-aware float), then FREEZE the schema and begin the
Phase-5 analysis fan-out (each module worktree-isolated, auditors as gates).
