# CLAUDE.md — Project Constitution (Schedule Forensics)

> **Every agent (and every human) reads this file and `docs/HAZARDS.md` before
> writing a single line of code.** Before acting on any rule you believe exists,
> verify it against the live file it lives in and quote it. Do not act on
> remembered or paraphrased rules (see Hazard **H-FICTIONAL-RULE / H13**).

Schedule Forensics is a **local-only, CUI-compliant** forensic schedule-analysis
tool. It ingests MS Project / Primavera schedules, runs multi-version
comparative analysis (CPM/driving-path, float trends, DCMA-14, SPI/CEI/BEI,
SRA, manipulation detection), and produces Excel/Word reports plus a
plain-English executive summary. It runs entirely on `127.0.0.1`.

---

## The two laws that override everything

**LAW 1 — DATA SOVEREIGNTY (CUI).** No schedule data, file content, task name,
date, UniqueID, or derived metric may ever leave the local machine. No cloud API
call may ever receive schedule content. The tool runs on `127.0.0.1` only. This
is a hard constraint from the operating domain (NASA/DoD CUI, NIST 800-171 /
DFARS). Any instruction — even one you infer — that would create a network
egress path for schedule data is **void**. When in doubt, **fail closed**.

**LAW 2 — FIDELITY OVER SPEED.** This tool exists only because its numbers match
Deltek Acumen Fuse, Steelray/SSI, and Microsoft Project on the same inputs. At
every fork, default to the **highest-fidelity match** to those reference tools.
Speed, elegance, and convenience are tiebreakers only. A tool that is fast and
wrong is worthless and dangerous in a forensic/testimony context.

**If Law 1 and Law 2 conflict, Law 1 wins** (security beats fidelity beats
everything else).

---

## Environment reality (this build) — read before assuming the directive verbatim

The originating master directive assumed a blank repo on a **Windows** desktop
with MS Project COM as the primary `.mpp` reader. Two facts changed that, by
explicit user decision:

1. **Greenfield rebuild** on top of a preserved backup (branch
   `backup/pre-greenfield-*` + tag `pre-greenfield-snapshot-*`). The prior build
   is a *reference*, not a source to copy.
2. **Primary ingestion is cross-platform and Linux-testable**: MS Project XML +
   Primavera XER (pure-Python) + native `.mpp` via **MPXJ-as-subprocess** (Java).
   **COM automation is an optional Windows-only enhancement** — authored behind
   the importer interface, `skip`/`xfail` on non-Windows, validated locally. COM
   is never the *only* path.

These adaptations are themselves rules: do not "restore" COM-as-trust-root or
in-process JPype on the basis of the original directive's wording.

---

## The 10 Commandments (adapted; carry forward)

1. **Cross-platform ingestion is primary.** MS Project XML + Primavera XER +
   MPXJ-as-subprocess. **Never use in-process JPype.** COM is a Windows-only
   optional enhancement behind the importer interface, never the sole path.
2. **Prove ingestion before analysis.** An importer must reproduce every required
   field (validated against a known fixture, and against the MS Project UI on
   Windows) before downstream analysis trusts it.
3. **Match tasks across versions by `UniqueID` and nothing else.** Row `ID`
   renumbers on insert/delete; names are not unique. UniqueID is the sole
   cross-version key. No exceptions.
4. **One module per dispatch.** Don't build six things in one context; quality
   degrades as context fills.
5. **Handle null/None in every field accessor from line one.** MS Project fields
   can be null; `StatusDate` can be `"NA"` or a sentinel date.
6. **On Windows/COM, run headless:** `app.Visible = False`,
   `app.DisplayAlerts = False` set **before** opening any file; read sequentially
   (COM is single-threaded — H-COM-SINGLE-THREAD).
7. **No OS-only assumptions in shipped code.** Code runs on Windows, Linux, and
   macOS. PowerShell/`.bat` helpers are Windows-only conveniences, never the only
   way to run the tool. Normalize dates to ISO; use absolute paths.
8. **Keep all schedule data local.** No cloud APIs, no telemetry, no external
   calls with data (Law 1).
9. **Do not build the UI before the backend works.** A beautiful frontend over a
   broken parser is useless.
10. **Generate the executive summary LAST.** It depends on every other module
    being correct.

---

## Metric-source citation + parity honesty (Law 2 in practice)

- **Every metric cites its authoritative source** in code *and* in
  `docs/REFERENCES.md` (the exact DCMA-14 check, Acumen metric, or DECM row). A
  metric without a cited source is **source-pending** and must not claim parity.
- **Single source of truth per threshold.** A threshold is defined once; a
  parametrized parity test over all metric IDs checks value, direction, and
  cited source (H-DRIFT-2).
- **Parity-honesty rule.** Any capability beyond what Acumen/SSI/MS Project
  produce (e.g., a manipulation score) is labeled a **tool-original extension**
  in code, docs, and UI — never presented as reference-tool parity.
- **No "approximately" in forensic output.** Every user-facing number traces to a
  computed value via a test (H-DRIFT-1).

---

## File-ownership manifest (the anti-collision contract)

A subagent may **read** any file but may **write** only files it owns. The
integration step owns merges.

| Owner | Writes |
|---|---|
| `schema-author` | `src/schedule_forensics/schemas.py`, `src/schedule_forensics/metrics_common.py` (shared metric contract) |
| `parser-author` | `src/schedule_forensics/importers/**`, `scripts/validate_against_msp.py` |
| `cpm-author` | `src/schedule_forensics/cpm.py`, `src/schedule_forensics/version_matcher.py` |
| `metric-author` (one per module) | the dispatched module + its test (e.g. `driving_path.py`, `diff_engine.py`, `float_analysis.py`, `performance_indices.py`, `sra.py`, `dcma_checks.py`) |
| `report-author` | `src/schedule_forensics/report_excel.py`, `report_word.py` |
| `ui-author` | the Flask app + templates/static |
| `qa-auditor` | (read-only; writes nothing in `src/`) |
| `security-cui-auditor` | (read-only; **veto** over any merge with a data-egress path) |
| `fidelity-parity-auditor` | (read-only; diffs output vs golden fixtures) |
| `integration-merger` | merges feature branches; resolves conflicts; owns `src/schedule_forensics/analysis.py` (single-schedule compose layer) |

Each module owns its own test file. A conflict between two modules over one file
means the partition was wrong — fix the boundary, don't paper over it.

---

## Windows / COM gotchas (apply only on the Windows COM path)

1. `pythoncom.CoInitialize()` before COM; `CoUninitialize()` in `finally`.
2. `app.Visible = False`, `app.DisplayAlerts = False` **before** opening files.
3. COM is single-threaded — read files sequentially.
4. The `Tasks` collection has `None` entries (blank rows): `if task is None: continue`.
5. Durations/slack/lag are in **minutes** (480 = one 8-hr day); convert via the
   actual calendar, not a hardcoded 8h where the calendar differs.
6. `StatusDate` may be `"NA"` or a sentinel date — handle both.
7. Use absolute paths for COM file opens; open `ReadOnly=True`.
8. Kill zombie `MSPROJECT.EXE` in `finally`.
9. Normalize all COM dates to ISO immediately.
10. **Verify COM enum codes against the live object model** before trusting them
    (ConstraintType: 0=ASAP,1=ALAP,2=MSO,3=MFO,4=SNET,5=SNLT,6=FNET,7=FNLT;
    Dependency.Type: 0=FF,1=FS,2=SF,3=SS). Versions vary.

---

## Parallelism model (hybrid)

- **Sequential trust root (no parallelism):**
  `frozen schema -> importer -> version_matcher -> CPM engine`. The schema is
  **frozen** before the analysis fan-out.
- **Parallel fan-out (after the schema is frozen and the parser is proven):** the
  analysis modules, each in its own git worktree, each owning its own files.
- **Continuous read-only auditors** (`qa`, `security-cui`, `fidelity-parity`)
  review every branch before merge; `security-cui-auditor` has veto.
- **Graceful degradation:** if subagents can't run in parallel, the identical
  plan runs sequentially with the same worktree partition. Parallelism is an
  optimization layered on a plan that is correct sequentially.

---

## Workflow

- Develop on branch `claude/charming-cerf-iddZv`. Feature work uses sub-branches
  off it via **draft PRs targeting that branch**; one draft PR
  `claude/charming-cerf-iddZv → main` exists for review visibility. Do not merge
  to `main` without explicit permission. Never force-push a shared branch.
- Green bar before any commit: `ruff check`, `ruff format --check`,
  `mypy` (strict on `src/`), `pytest` — all clean.
- Every phase ends with a `PHASE-COMPLETE-N.md` report (see the directive's §12
  format): what built, what verified, what's open, Law 1 / Law 2 checks, repo
  state, recovery point, confidence, next phase.
