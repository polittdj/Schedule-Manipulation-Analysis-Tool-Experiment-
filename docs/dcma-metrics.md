# DCMA Metrics 1-4

Each metric is a pure function `run_<name>(schedule, options) -> MetricResult`. Severity is
**binary PASS/FAIL** against a single cited threshold (see
`FIDELITY-DECISION-dcma-severity.md`). A metric whose denominator would be zero **raises**
`MetricError` rather than fabricating a result. Offenders are sorted by UniqueID (deterministic).

| # | Name | Numerator / Denominator | Threshold | Offenders | Offender `value` |
|---|------|-------------------------|-----------|-----------|------------------|
| 1 | Logic (Missing Pred/Succ) | tasks missing a pred and/or succ / all tasks | `<= 5%` | the missing-logic tasks | # of missing ends (1 or 2) |
| 2 | Leads (Negative Lag) | relations with `lag < 0` / all relations | `0%` (any lead fails) | the lead relations | lag minutes (negative) |
| 3 | Lags (Positive Lag) | relations with `lag > 0` / all relations | `<= 5%` | the lagged relations | lag minutes (positive) |
| 4 | Relationship Types | FS relations / all relations | `>= 90%` | the **non-FS** relations | predecessor UniqueID |
| 5 | Hard Constraints | tasks with a hard constraint (MSO/MFO/SNLT/FNLT) / all tasks | `<= 5%` | the hard-constrained tasks | flag (1.0) |
| 6 | High Float | tasks with total float > 44 working days / all tasks | `<= 5%` | the high-float tasks | total float (working days) |
| 7 | Negative Float | tasks with total float < 0 / all tasks | `0%` (any negative fails) | the negative-float tasks | total float (working days) |
| 8 | High Duration | tasks with duration > 44 working days / all tasks | `<= 5%` | the long tasks | duration (working days) |
| 9 | Invalid Dates | tasks with actuals after the data date or inconsistent progress / all tasks | `0%` | the offending tasks | flag (1.0) |
| 10 | Resources | detail tasks (duration > 0) missing a resource / detail tasks | `<= 5%` | the unresourced tasks | flag (1.0) |
| 11 | Missed Tasks | tasks due by the data date that finished late/not at all / tasks due | `<= 5%` | the missed tasks | flag (1.0) |

Notes:
- Metric 4 is an AT_LEAST metric: the numerator counts the *good* (FS) relations while the
  offenders are the *complement* (non-FS). `MetricResult.percentage` is the FS%.
- Relation-based offenders are keyed by the **successor** UniqueID (the task receiving the tie).
- Metric 1 `MetricOptions(exclude_project_bookends=True)` exempts a lone open start and a lone
  open finish (the DCMA convention that one start milestone may legitimately lack a predecessor
  and one finish milestone may lack a successor). The default is the strict literal count.
- Thresholds are the canonical DCMA 14-Point Assessment values; citations are by assessment name
  because the primary sources were unavailable this session (see
  `FIDELITY-COMPROMISE-dcma-citations.md`).
- **Metrics 6/8** convert minutes to working days per each task's own calendar; the "44 working
  days" bar is the canonical DCMA threshold. Metric 6 (High Float) consumes the CPM total float;
  Metric 8 (High Duration) uses the single modelled duration as the baseline duration.
- **Metric 7 (Negative Float)** is driven by task **deadlines** / hard constraints (which cap the
  late finish without rescheduling, so a miss yields negative total float). Offender ``value`` =
  total float in working days.
- **Metrics 9/10/11** read the tracking data (status date, actual dates, baseline finishes,
  resources) added to the model. They raise `MetricError` when the required data is absent (e.g.
  no `status_date`), so the `/analyze` report lists them as *skipped* rather than fabricating a PASS.
  Metric 9's complementary "forecast remaining work before the data date" sub-check is deferred —
  it needs data-date (progress) scheduling in the CPM engine.
- **Coverage:** Metrics 1-11 are implemented; 12 (Critical Path Test), 13 (CPLI), 14 (BEI) follow.
