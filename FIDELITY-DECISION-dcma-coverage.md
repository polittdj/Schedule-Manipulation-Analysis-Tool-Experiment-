# FIDELITY-DECISION — DCMA metric coverage (all 14) and its simplifications

**All 14 DCMA 14-Point metrics are implemented**, each as a pure function with known-answer tests:
1 Logic, 2 Leads, 3 Lags, 4 Relationship Types, 5 Hard Constraints, 6 High Float, 7 Negative
Float, 8 High Duration, 9 Invalid Dates, 10 Resources, 11 Missed Tasks, 12 Critical Path Test,
13 CPLI, 14 BEI.

The model grew to support them (status date, actual start/finish, baseline finishes, percent
complete, resources; project baseline finish), and the CPM engine grew date constraints + deadlines.
Metrics that need data which a given schedule lacks **raise `MetricError`**, so `/analyze` reports
them as *skipped* rather than fabricating a result.

## Documented simplifications (faithful where it counts; honest where it's reduced)

1. **No progress / data-date (re)scheduling.** The CPM forecasts every task from `project_start`
   using pure logic; it does not reschedule remaining work to start at the data date, nor consume
   recorded actuals to compute remaining duration. Consequences:
   - **Metric 9 (Invalid Dates)** implements the unambiguous checks — actual dates after the data
     date, and progress/actual-date inconsistencies — but **omits** the "forecast remaining work
     scheduled before the data date" sub-check, which requires data-date scheduling.
   - Forecast dates used by CPLI (13) come from the logic forward pass, not from a status-aware
     reschedule. For an un-progressed (or freshly-statused) schedule this matches; for a
     mid-execution schedule a real tool would reschedule remaining work first.

2. **Metric 10 (Resources) threshold.** DCMA references vary on this one (often informational);
   implemented as "≤ 5% of detail tasks missing a resource," a defensible reading. Citation
   caveat per `FIDELITY-COMPROMISE-dcma-citations.md` applies.

3. **`ALAP` constraints** are rejected by the CPM (`CPMError`) rather than mis-scheduled — see
   `FIDELITY-DECISION-cpm-engine.md`.

These are the honest edges of a faithful 14-metric implementation; closing #1 (a status-aware
progress-scheduling pass) is the main remaining fidelity upgrade.
