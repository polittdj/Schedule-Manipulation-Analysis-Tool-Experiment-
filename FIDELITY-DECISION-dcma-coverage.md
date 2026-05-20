# FIDELITY-DECISION — which DCMA metrics are implemented vs. deferred

DCMA's full assessment has 14 points. This build implements the ones that are computable from
the current data model + CPM output without inventing data:

**Implemented:** 1 (Logic), 2 (Leads), 3 (Lags), 4 (Relationship Types), 6 (High Duration),
7 (High Float), 8 (Negative Float). Metrics 6/7/8 reuse the existing model + CPM output,
converting minutes to working days per each task's calendar. Metric 8 became implementable once
**task deadlines** were added (a deadline caps the late finish, so a missed deadline yields the
negative float Metric 8 needs — fully testable).

**Deferred — and why (each would need model fields I have not added, so building them now would
mean fabricating inputs or shipping a check that can't be exercised):**
- **5 Hard Constraints** — requires scheduling constraints (MSO/MFO/SNLT/FNLT). Modelling them
  without faithful CPM scheduling support would risk silently-wrong dates, so this is deferred
  with the constraint-scheduling work (deadlines, which only affect late dates, were safe to add;
  hard constraints, which reschedule, are not yet).
- **9 Invalid Dates, 11 Missed Tasks, 13 Baseline Execution Index** — require actual/forecast and
  baseline dates, which the model does not carry.
- **10 Resources, 12 Critical Path Test / CPLI, 14 (program-specific)** — require resource
  assignments and/or a baseline.

Decision rationale: the experiment forbids shipping code I know is wrong or half-finished. A
metric whose failure path cannot be produced or whose inputs don't exist would be exactly that.
Implementing 6, 7, and 8 (fully testable, real inputs) and explicitly deferring the rest is the
faithful, honest scope. The same by-name citation caveat as Metrics 1-4 applies
(`FIDELITY-COMPROMISE-dcma-citations.md`).
