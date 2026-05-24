# Golden-file parity harness

> **Purpose (LAW 2 — fidelity over speed):** this tool exists only because its
> numbers match Deltek Acumen Fuse, Steelray/SSI, and Microsoft Project on the
> same inputs. The parity harness makes that claim *checkable*: pair an input
> schedule with the values a reference tool produced for it, and the harness
> re-runs this tool on the same input and diffs every value within a stated
> tolerance — citing which reference tool each expected number came from.

This is **scaffolding that is ready for your reference numbers.** It ships with a
single in-repo case that is *self-generated* (a regression baseline), explicitly
**not** a parity claim. Real parity needs reference-tool outputs that only you can
supply (see "Add a reference-tool case" below). That hand-off is by design.

## Run it

```sh
# Default root: tests/fixtures/golden (the in-repo synthetic/self cases)
python scripts/parity_report.py

# Real cases kept locally, OUTSIDE the repo (CUI inputs — LAW 1):
python scripts/parity_report.py --root /path/to/your/local_parity
```

Exit code: `0` if every check in every case is within tolerance, `1` on any drift
or malformed case, `2` if no cases are found. The pytest suite
(`tests/test_parity.py`) also runs every case under `tests/fixtures/golden/`, so
drift fails CI.

## LAW 1 — real schedule data is CUI, never commit it

- Real `.mpp` / `.xer` / XML inputs and any expected values derived from them are
  **CUI**. Keep real cases in a directory **outside** the repo, or under
  `local_parity/` (git-ignored), and point `--root` at it.
- Only **synthetic / non-CUI** cases belong under `tests/fixtures/golden/`.
- The harness is fully local: it reads files and computes — there is no network
  path, no upload, no telemetry.

## Case format

A case is a directory containing `case.json` and its input file:

```
<case_dir>/
  case.json
  input.xml          # or input.xer / input.json
```

```jsonc
{
  "case": "acme_baseline_vs_acumen",
  "input": "input.xml",                         // .xml (MSPDI) | .xer | .json
  "reference_tool": "Deltek Acumen Fuse 8.2",   // who produced the expected values
  "notes": "Acumen 'Schedule' analysis, default DCMA thresholds, 2025-03-01 status.",
  "checks": [
    {"metric": "project_finish_minutes", "expected": 2400, "tolerance": 0,
     "source": "Acumen Fuse 8.2, Schedule view, Finish offset"},
    {"metric": "health_score_percent",   "expected": 72.73, "tolerance": 0.5,
     "source": "Acumen Fuse 8.2, DCMA pass rate"},
    {"metric": "critical_path",           "expected": [1, 2, 4],
     "source": "MS Project 2019, total_float <= 0"},
    {"metric": "dcma:DCMA-04:measured",   "expected": 100.0, "tolerance": 0.0,
     "source": "Acumen DCMA #4 (% FS) "},
    {"metric": "dcma:DCMA-04:status",     "expected": "PASS",
     "source": "Acumen DCMA #4"}
  ]
}
```

### Supported `metric` keys

| Key | Resolves to |
|---|---|
| `project_finish_minutes` | CPM project finish (working-minute offset) |
| `project_finish_days` | project finish / 480 |
| `health_score_percent` | DCMA integrity score |
| `critical_path` | UniqueID list (exact match) |
| `driving_chain` | UniqueID list (exact match) |
| `dcma:<ID>:measured` | a DCMA metric's measured value (e.g. `dcma:DCMA-04:measured`) |
| `dcma:<ID>:status` | `PASS` / `FAIL` / `SKIPPED` |
| `dcma:<ID>:threshold` | the metric threshold |
| `index:<ID>:measured` | a performance index value (`index:SPI:measured`, `index:SPI(t):measured`) |
| `index:<ID>:status` | the index status |

### Comparison rules

- **Numbers** must be within `tolerance` (default `0`). Pick a tolerance that
  reflects the reference tool's rounding (e.g. `0.5` if it reports whole percent).
- **Lists** (`critical_path`, `driving_chain`) and **strings** (`status`) match
  exactly. A status is compared by name (`"PASS"`).
- An **unknown metric key** or **malformed case** raises and fails the run — the
  harness fails loud rather than silently passing a typo.

## Add a reference-tool case

1. Pick an input schedule you also have reference-tool output for. Export it to
   **MS Project XML** (`.xml`) if it is a native `.mpp` — the harness reads text
   formats directly and does not shell out to a converter.
2. Create `<case_dir>/` with the input file and a `case.json`.
3. Fill `checks` with the reference tool's numbers, each with a `source` that
   names the tool/version and where the number came from. Set tolerances to match
   the reference tool's reported precision.
4. Run `python scripts/parity_report.py --root <parent_of_case_dir>` and
   investigate any `DRIFT` lines.

## Parity-honesty (LAW 2)

The `reference_tool` and per-check `source` fields are the parity claim. A case
sourced from this tool itself (like the in-repo `simple_network_self`) is a
**regression baseline only** and must say so — it is never evidence that the tool
matches Acumen/SSI/MS Project. Only a case whose expected values come from a real
reference tool substantiates parity, and only for the metrics it actually checks.
