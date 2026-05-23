# HAZARDS — carried-forward failure modes (read before coding)

Real failure modes paid for in prior builds, plus hazards specific to this
environment. Every agent reads these first. Mitigations are enforced by tests
and review gates, not good intentions.

## Carried-forward hazards

- **H-DRIFT-1 (numeric fidelity drift).** Derived/rendered numbers can silently
  diverge from inputs (a model once reported ~82% when the input was 78%).
  *Mitigation:* every user-facing number traces to a computed value, asserted by
  a test. No "approximately" in forensic output.

- **H-DRIFT-2 (double-sourced thresholds drift).** A threshold transcribed into
  more than one place drifts. *Mitigation:* single source of truth per threshold;
  a parametrized parity test over all metric IDs checks value, direction, and
  cited source. Verify the detector works by perturbing one threshold and
  confirming the test fails.

- **H-FICTIONAL-RULE (H13).** Memory/old handoffs carry authoritative-looking
  "rules" that cite sections but don't exist in the live code. *Mitigation:*
  verify every cited rule against the live file before acting; quote it as
  evidence.

- **H-VACUOUS-TEST.** A green suite proves nothing if the tests assert nothing.
  *Mitigation:* perturbation discipline — for each critical calc, a test must
  FAIL when the input is perturbed. `qa-auditor` independently re-runs this.
  (Live examples: `test_perturbation_flips_criticality`,
  `test_duration_mutation_is_actually_read`, and the schema "rejects invalid"
  tests.)

- **H-COM-SINGLE-THREAD.** MS Project COM is single-threaded per apartment. Never
  parallelize file reading on the COM path; read sequentially.

- **H-SCOPE-CREEP.** Building the whole tool in one context degrades output.
  *Mitigation:* phase gates + one module per dispatch.

- **H-WINDOWS.** On the COM path: PowerShell, file-locking (MS Project locks open
  `.mpp`), absolute paths, ISO-date normalization on every COM date.

## Environment-specific hazards (this build)

- **H-NO-COM-HERE.** This session runs on Linux: no Windows, no MS Project COM,
  no PowerShell. The COM importer cannot run or be tested here. *Mitigation:* COM
  lives behind the importer interface and is `skip`/`xfail` off-Windows; a
  conformance test (`COM output == MPXJ output` on a shared fixture) runs only on
  the user's Windows box. The primary path (XML/XER/MPXJ-subprocess) is fully
  testable here.

- **H-PYTHON-VERSION.** Both Python 3.11.15 and 3.13.12 are present; the default
  `python3` and `pip` are 3.11. *Mitigation:* target **3.11+** (`requires-python
  = ">=3.11"`, `target-version = py311`) so the green bar runs with the default
  interpreter; avoid 3.12/3.13-only syntax.

- **H-MSPDI-LAG-UNIT (source-pending).** The MSPDI `<LinkLag>` unit
  (tenths-of-a-minute assumption) is **not yet verified** against the official
  schema. *Mitigation:* golden fixtures use `LinkLag=0` so no asserted value
  depends on the conversion; the importer documents the assumption and the
  conversion is isolated for later correction. Lag arithmetic in the CPM is
  tested with explicit minute values (no XML, no unit ambiguity).

- **H-MSPDI-DURATION-DAYS (source-pending).** MSPDI `<Duration>` is ISO-8601;
  MS Project encodes working hours in the span, so total span minutes == working
  minutes. Calendar-day-encoded durations (`P2D...`) would need calendar-aware
  conversion. *Mitigation:* fixtures use `PT...H` forms only; documented in the
  importer.

- **H-CONSTRAINT-DATETIME (source-pending).** The CPM honors SNET/FNET/SNLT/FNLT
  + deadlines under MS Project's "honor constraint dates" mode (conflicts surface
  as negative float). The `datetime_to_offset` mapping uses working-day
  granularity + a clamped intraday term; the exact intraday/non-working-day and
  honor-mode semantics are a defined model **pending live-MS Project validation**
  (unavailable on Linux). ALAP/MSO/MFO are deferred: the engine RAISES rather than
  emit a silently-wrong schedule. Tests use 08:00 day-aligned constraint dates so
  expected offsets are exact.

- **H-CALENDAR-DEFERRED.** The MSPDI `<Calendars>` block is not yet parsed; the
  default `Calendar` (480 min/day, Mon-Fri) is used. Multi-shift / per-task
  calendars and lunch breaks are deferred. *Mitigation:* documented in the
  importer and schema; fixtures chosen to match the default calendar.

- **H-GITIGNORE-JSON.** The master directive's `.gitignore` listed `*.json`
  globally, which would block tracked config (`.claude/settings.json`, package
  manifests). *Mitigation (deliberate deviation):* we do **not** globally ignore
  `*.json`; schedule JSON is blocked via the runtime data directories
  (`uploads/`, `session_data/`, `exports/`). All other schedule formats
  (`.mpp/.mpx/.xer/.xml/.csv`) are globally ignored, with a single negation that
  re-includes `tests/fixtures/**` (synthetic data only).
