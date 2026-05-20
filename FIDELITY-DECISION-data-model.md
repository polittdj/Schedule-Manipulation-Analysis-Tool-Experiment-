# FIDELITY-DECISION — M2 data model

Decisions made building the strict/frozen Pydantic models. None lose forensic
information; each is a deliberate, defensible choice.

1. **Collections are sorted tuples, never sets.** `holidays`, `working_weekdays`,
   `tasks`, `relations`, `calendars`. Sets iterate in hash-seed-dependent order, which
   breaks the byte-equal JSON round-trip the milestone requires. A `field_validator`
   sorts + dedups `holidays`/`working_weekdays` so two logically-equal calendars
   serialize identically. No semantic loss.

2. **Naive datetimes for `project_start`.** Timezone-aware datetimes can round-trip to
   equal-but-not-byte-identical strings, and a schedule runs on its own clock. Tz-aware
   handling is out of M1–M5 scope. Revisit when a real parser reads files that carry tz.

3. **Calendars are a tuple on `Schedule` with `Task.calendar_id` referencing by id**, not
   a single nested calendar. MS Project schedules share a handful of calendars across many
   tasks; referencing avoids duplicate (and potentially byte-different) copies and matches
   the real domain. A `model_validator` enforces referential integrity. NOTE: the M4 CPM
   engine still assumes a single shared calendar for its working-minute offset axis;
   cross-calendar arithmetic is logged separately at M4.

4. **`strict=True` + `extra="forbid"` + `frozen=True` on all four models.** Forensic inputs
   must not be silently coerced (`"5"`→5, `5.0`→5 are rejected), must not carry unmodeled
   fields, and must be immutable once constructed (evidence shouldn't mutate). Identity is
   `Task.unique_id` only — never name or any external id.
