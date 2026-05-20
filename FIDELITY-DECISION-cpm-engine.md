# FIDELITY-DECISION — M4 CPM engine

1. **Working-minute offset axis.** ES/EF/LS/LF/slack are integer working-minute offsets from
   `project_start`. Exact integer arithmetic, hand-verifiable, and it makes the end-of-day /
   start-of-next-day boundary ambiguity structurally impossible (a finish and the start it
   drives share one offset). Working days for presentation = `minutes / (hours_per_day*60)`.

2. **Durations and lags are working-time minutes** (MS Project's default), not elapsed time.
   Elapsed-duration ("ed") tasks and elapsed lags are a real but secondary MSP feature and are
   out of scope here. Negative lag (lead) simply subtracts working minutes.

3. **Single shared calendar for the offset axis.** The model permits multiple calendars
   (`Task.calendar_id`), but the engine treats the offset axis as one calendar's working time.
   Multi-calendar schedules make `EF(P) + L` ambiguous when predecessor and successor differ;
   cross-calendar conversion is deferred. Known-answer tests use one calendar, so they are exact.

4. **As-soon-as-possible, no constraints.** SNET/MSO/deadline constraints and negative float
   are not modelled in M4; every task starts as early as its logic allows. With no constraints,
   zero-total-slack and longest-path coincide (so "critical = total_slack == 0" is exact here).
   This is the standard simplification for a first CPM pass; constrained scheduling is later work.

5. **`critical_path` is a `tuple`, not the spec's `list`.** A frozen dataclass with a `list`
   field is only shallow-immutable; a tuple makes the result genuinely immutable (and hashable).
   Minor, intentional deviation. Same reasoning for `timings`.

6. **Free slack clamped implicitly by construction, not arbitrarily.** Because ES is the max over
   predecessors, each successor gap is >= 0, so free slack is naturally non-negative; no manual
   clamp is applied (a clamp could mask an off-by-one — known-answer tests assert exact values).
