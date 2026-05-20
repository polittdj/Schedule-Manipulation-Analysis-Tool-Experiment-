# FIDELITY-DECISION — which DCMA metrics are implemented vs. deferred

DCMA's full assessment has 14 points. This build implements the ones that are computable from
the current data model + CPM output without inventing data:

**Implemented:** 1 (Logic), 2 (Leads), 3 (Lags), 4 (Relationship Types), 5 (Hard Constraints),
6 (High Duration), 7 (High Float), 8 (Negative Float) — DCMA Metrics 1-8. Metrics 6/7/8 reuse the
model + CPM output (working-day conversions). Metric 8 became implementable with **task deadlines**,
and Metric 5 with **date-constraint support** in the CPM engine (now that constraints are modelled
and faithfully scheduled, counting the hard ones is exact and testable).

**Deferred — each needs model fields I have not added, so building them now would mean fabricating
inputs or shipping a check that can't be exercised:**
- **9 Invalid Dates, 11 Missed Tasks, 13 Baseline Execution Index** — require actual/forecast and
  baseline dates, which the model does not carry.
- **10 Resources, 12 Critical Path Test / CPLI, 14 (program-specific)** — require resource
  assignments and/or a baseline.

Decision rationale: the experiment forbids shipping code I know is wrong or half-finished. A
metric whose failure path cannot be produced or whose inputs don't exist would be exactly that.
Implementing 5, 6, 7, and 8 (fully testable, real inputs) and explicitly deferring the rest is the
faithful, honest scope. The same by-name citation caveat as Metrics 1-4 applies
(`FIDELITY-COMPROMISE-dcma-citations.md`).
