# REFERENCES — authoritative source manifest (Law 2)

Every metric and every threshold cites its authoritative source here **and** in
code. A metric without a cited source is **source-pending** and must not claim
reference-tool parity. Tool-original capabilities are labeled **extension** and
are never presented as parity.

## How to use this file

- `docs/sources/` holds the **public** reference documents (PDF/XLSX). They are
  safe to keep in-repo. (Real schedule data is never committed — see LAW 1.)
- Each metric, when implemented, gets a row in the metric table below with: the
  metric ID, the exact formula/threshold, the cited source + locator (page/row),
  and a `status` of `cited` or `source-pending` or `extension`.

## Intended authoritative sources (to be placed in `docs/sources/`)

| Key | Document | Used for |
|---|---|---|
| ACUMEN | Deltek Acumen Metric Developer's Guide | Acumen metric semantics; comparative `ProjectTimeNow` / `ProjectPreviousTimeNow` |
| DECM8 | Deltek DECM 8.0 metrics workbook | metric definitions + thresholds (DECM rows) |
| DCMA-EDWARDS | DCMA 14-Point Assessment (Edwards, 2016) | DCMA-14 checks + thresholds |
| DCMA-WINTER | DCMA 14-Point Assessment (Ron Winter, 2011) | DCMA-14 checks + thresholds |
| NASA-EVM | NASA EVM Implementation Handbook | SPI / SPI(t) / earned-schedule, BEI semantics |
| SSI-SLACK | Steelray/SSI driving-slack methodology | driving-path / relationship-slack semantics |

> Status: documents not yet supplied to `docs/sources/`. Until present, the
> metrics that depend on them are **source-pending** (threshold *values* may be
> the well-known canonical numbers, but page/row anchoring is unverified — this
> is logged honestly rather than claimed as parity).

## Metric → source table

_(Populated as metrics are implemented in Phase 5. Empty now — no analysis
metrics ship in the trust-root spine.)_

| Metric ID | Definition / threshold | Source + locator | Status |
|---|---|---|---|
| `driving_path` | Driving-path trace: relationship free float == 0 marks a binding ("driving") link; back-trace from the project-finish driving sink | SSI-SLACK (Steelray/SSI driving-slack methodology) | cited (practice); page-anchor source-pending |
| `DCMA-01` Missing Logic | ≤ 5% of tasks lack a predecessor or successor | DCMA-EDWARDS / DCMA-WINTER 14-pt M1 | value canonical; page-anchor source-pending |
| `DCMA-02` Leads | == 0 relationships with negative lag | DCMA-EDWARDS / DCMA-WINTER 14-pt M2 | value canonical; page-anchor source-pending |
| `DCMA-03` Lags | ≤ 5% of relationships carry positive lag | DCMA-EDWARDS / DCMA-WINTER 14-pt M3 | value canonical; page-anchor source-pending |
| `DCMA-04` Relationship Types | ≥ 90% of relationships are Finish-to-Start | DCMA-EDWARDS / DCMA-WINTER 14-pt M4 | value canonical; page-anchor source-pending |
| `DCMA-05` Hard Constraints | ≤ 5% of tasks carry a hard constraint (MSO/MFO/SNLT/FNLT) | DCMA-EDWARDS / DCMA-WINTER 14-pt M5 | value canonical; page-anchor source-pending |
| `DCMA-06` High Float | ≤ 5% of incomplete tasks with total float > 44 working days | DCMA-EDWARDS / DCMA-WINTER 14-pt M6 | value canonical; page-anchor source-pending |
| `DCMA-07` Negative Float | == 0% of tasks with negative total float | DCMA-EDWARDS / DCMA-WINTER 14-pt M7 | value canonical; page-anchor source-pending |
| `DCMA-08` High Duration | ≤ 5% of incomplete tasks with duration > 44 working days | DCMA-EDWARDS / DCMA-WINTER 14-pt M8 | value canonical; page-anchor source-pending |
| `DCMA-09` Invalid Dates | == 0% of tasks have dates inconsistent with the status date (future actuals / forecast-in-past) | DCMA-EDWARDS / DCMA-WINTER 14-pt M9 | value canonical; page-anchor source-pending |
| `DCMA-10` Resources | ≤ 5% of incomplete tasks (duration > 0) lack a resource | DCMA-EDWARDS / DCMA-WINTER 14-pt M10 | value canonical; page-anchor source-pending |
| `DCMA-11` Missed Tasks | ≤ 5% of baselined tasks finish (or forecast) past baseline | DCMA-EDWARDS / DCMA-WINTER 14-pt M11 | value canonical; page-anchor source-pending |
| `DCMA-12` Critical Path Test | an injected critical-path delay must flow to the project finish (pass/fail) | DCMA-EDWARDS / DCMA-WINTER 14-pt M12 | value canonical; page-anchor source-pending |
| `DCMA-13` CPLI | ≥ 0.95: (baseline−status) / (forecast−status), working-minute offsets | DCMA-EDWARDS / DCMA-WINTER 14-pt M13 | value canonical; page-anchor source-pending |
| `DCMA-14` BEI | ≥ 0.95: tasks completed / tasks baselined-due by the status date | DCMA-EDWARDS / DCMA-WINTER 14-pt M14 | value canonical; page-anchor source-pending |
| `sra` | Monte-Carlo SRA: BetaPERT 3-point sampling → P50/P80/P95 + per-task criticality index (default spread O=0.75D, M=D, P=1.5D) | SRA-MONTE-CARLO / BETA-PERT (Acumen Fuse Risk; Primavera Risk Analysis) | method cited (practice); default spread is a **tool default**, not parity; page-anchor source-pending |
| `SPI` | Schedule Performance Index = EV/PV = BCWP/BCWS (PV time-phased by linear baseline spend); ≥ 0.95 common EVM management threshold (NOT a DCMA-14 number). Needs schema v1.1.0 `budgeted_cost`+`baseline_start`; SKIPPED without them | NASA-EVM (SPI = BCWP/BCWS) | method cited (practice); 0.95 is a management threshold, not DCMA; page-anchor source-pending |
| `SPI(t)` | Earned-Schedule SPI(t) = ES/AT; ES inverts the baseline PV curve to the time matching current EV; ≥ 0.95 common management threshold. Needs schema v1.1.0 fields; SKIPPED without them | NASA-EVM / Lipke "Earned Schedule" | method cited (practice); 0.95 is a management threshold, not DCMA; page-anchor source-pending |
| `CEI` Current Execution Index | Per-period count ratio: tasks that actually finished in `(prior.status_date, current.status_date]` ÷ non-summary, incomplete tasks the prior version FORECAST (frozen `Task.finish`) to finish in that period. Finish-only; per-period; capped at 1.0; needs ≥2 status-dated versions (else "insufficient data"). Threshold ≥0.95 | PASEG 10.4.5; NDIA IPMD "Managing Programs Using Predictive Measures" | method cited; **0.95 threshold source-pending (VERIFY** — NDIA prefers a >75th-pct trend); auto-snapshot capture is a **tool-original method** (metric standard, capture ours) |
| `diff_engine` | Objective version-pair deltas (duration/float/date shifts, became-critical/recovered, predecessor add/remove); UniqueID-matched, absolute-status-date ordered | ACUMEN comparative (`ProjectTimeNow`/`ProjectPreviousTimeNow`); deltas are arithmetic | objective facts; comparative frame cited (practice); page-anchor source-pending |
| `float_analysis` | Float burn-rate + trend bands CRITICAL / SEVERE_EROSION (≤−10d) / ERODING (<−1d) / STABLE / IMPROVING (>+1d) | **tool-original extension** — thresholds are tool defaults, not from DCMA/DECM/Acumen | **EXTENSION** — never presented as reference-tool parity |
| `exec_summary` health band | GREEN (≥90%) / YELLOW (≥70%) / RED (else, or any negative float) over the DCMA integrity score | **tool-original extension** — a synthesis over DCMA outcomes | **EXTENSION** — never presented as reference-tool parity |

## Foundational semantics cited by the trust-root spine

| Item | Definition used | Source | Status |
|---|---|---|---|
| Cross-version task identity | `Task.unique_id` only (never row `ID`, never name) | ACUMEN / general CPM practice | cited (practice) |
| Comparative version ordering | absolute `status_date` (`ProjectTimeNow` pattern), never relative offsets | ACUMEN | cited (practice); page-anchor source-pending |
| Critical path | `total_float <= 0` | MS Project behaviour; DCMA-14 critical-path semantics | cited (practice); page-anchor source-pending |
| Working-minute axis | durations/lags in working minutes; 480 = one 8h day | MS Project duration model | cited (practice) |
| MSPDI ConstraintType / link-Type codes | 0=ASAP..7=FNLT; link 0=FF,1=FS,2=SF,3=SS | MS Project object model / MSPDI | cited; verify per-version on Windows |
| MSPDI `<LinkLag>` unit | tenths-of-a-minute (assumed) | MSPDI schema | **source-pending** (H-MSPDI-LAG-UNIT) |
| XER structure / identity | tab-delimited `%T`/`%F`/`%R`/`%E` records; UniqueID = `TASK.task_id` (never `task_code`); `TASKPRED.task_id`=successor, `pred_task_id`=predecessor; duration `target_drtn_hr_cnt` (hours x60 = working min); lag `lag_hr_cnt` (hours, signed) | Oracle Primavera P6 XER import/export format (P6 schema: PROJECT/TASK/TASKPRED) | cited (practice); page-anchor source-pending |
| XER `pred_type` codes | PR_FS=FS, PR_SS=SS, PR_FF=FF, PR_SF=SF | Primavera P6 relationship-type enumeration | cited (practice); verify per-version |
| XER `cstr_type` codes | CS_ALAP=ALAP, CS_MSO=MSO, CS_MEO=MFO, CS_MSOA=SNET, CS_MSOB=SNLT, CS_MEOA=FNET, CS_MEOB=FNLT; unknown/blank=ASAP | Primavera P6 constraint enumeration | **source-pending** (verify against live P6; fixture asserts no value that depends on it) |
