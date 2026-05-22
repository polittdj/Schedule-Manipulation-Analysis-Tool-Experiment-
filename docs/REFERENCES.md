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

## Foundational semantics cited by the trust-root spine

| Item | Definition used | Source | Status |
|---|---|---|---|
| Cross-version task identity | `Task.unique_id` only (never row `ID`, never name) | ACUMEN / general CPM practice | cited (practice) |
| Comparative version ordering | absolute `status_date` (`ProjectTimeNow` pattern), never relative offsets | ACUMEN | cited (practice); page-anchor source-pending |
| Critical path | `total_float <= 0` | MS Project behaviour; DCMA-14 critical-path semantics | cited (practice); page-anchor source-pending |
| Working-minute axis | durations/lags in working minutes; 480 = one 8h day | MS Project duration model | cited (practice) |
| MSPDI ConstraintType / link-Type codes | 0=ASAP..7=FNLT; link 0=FF,1=FS,2=SF,3=SS | MS Project object model / MSPDI | cited; verify per-version on Windows |
| MSPDI `<LinkLag>` unit | tenths-of-a-minute (assumed) | MSPDI schema | **source-pending** (H-MSPDI-LAG-UNIT) |
