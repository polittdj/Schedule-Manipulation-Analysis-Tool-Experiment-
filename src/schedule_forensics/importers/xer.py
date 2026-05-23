"""Primavera P6 XER importer -- pure-Python, deterministic, no network I/O.

Cross-platform (Linux-testable) ingestion path for Oracle Primavera P6
schedules exported as ``.xer`` (the tab-delimited text interchange format).

XER structure: a header line (``ERMHDR``) followed by repeating table blocks.
Each block is introduced by ``%T <table>``, then a ``%F`` field-name row, then
one or more ``%R`` data rows; the file ends with ``%E``. ``%R`` values align
positionally with the preceding ``%F`` field names, so fields are read by NAME
(never by fixed column offset).

Fidelity notes (LAW 2):
  * **UniqueID = TASK.task_id** (the P6 activity object id), per CLAUDE.md
    commandment 3 -- never ``task_code`` (the human-facing Activity ID, which is
    not guaranteed unique across projects and can be renumbered).
  * **Durations:** ``TASK.target_drtn_hr_cnt`` is the planned/original duration
    in *working hours*; converted x60 to working minutes, consistent with the
    default 8h / 480-min calendar. Calendar-aware conversion (non-8h day) is
    deferred (docs/HAZARDS.md, H-CALENDAR-DEFERRED).
  * **Relationships (TASKPRED):** ``task_id`` is the SUCCESSOR and
    ``pred_task_id`` the PREDECESSOR; ``pred_type`` in
    {PR_FS, PR_SS, PR_FF, PR_SF}; ``lag_hr_cnt`` is working hours (negative ==
    lead), converted x60 to minutes.
  * **Project frame:** ``project_start`` = ``PROJECT.plan_start_date``;
    ``status_date`` (the P6 data date / ``ProjectTimeNow`` analogue) =
    ``PROJECT.last_recalc_date``. A multi-project XER is reduced to the single
    project owning the most tasks (a Schedule == one project at one status date).
  * **Constraints:** ``cstr_type`` is mapped for the standard P6 codes; an
    unknown or blank value maps to ASAP. This mapping is SOURCE-PENDING (verify
    against the live P6 object model). The synthetic fixture uses no constraints,
    so no asserted test value depends on it (mirrors the MSPDI lag-unit policy).

Source: Oracle Primavera P6 XER import/export format; table/field names per the
P6 schema (PROJECT, TASK, TASKPRED). See docs/REFERENCES.md.
"""

from __future__ import annotations

import datetime as dt
import os
from collections import Counter
from pathlib import Path

import pydantic

from schedule_forensics.schemas import (
    Calendar,
    ConstraintType,
    Relation,
    RelationType,
    Schedule,
    Task,
)


class ImporterError(ValueError):
    """Raised when an XER document cannot be parsed into a Schedule."""


# P6 TASKPRED.pred_type -> RelationType.
_RELATION_BY_XER: dict[str, RelationType] = {
    "PR_FS": RelationType.FS,
    "PR_SS": RelationType.SS,
    "PR_FF": RelationType.FF,
    "PR_SF": RelationType.SF,
}

# P6 TASK.cstr_type (primary constraint) -> ConstraintType. SOURCE-PENDING:
# verify against the live P6 object model (see docs/REFERENCES.md).
_CONSTRAINT_BY_XER: dict[str, ConstraintType] = {
    "CS_ALAP": ConstraintType.ALAP,  # As Late As Possible
    "CS_MSO": ConstraintType.MSO,  # Mandatory Start / Start On
    "CS_MEO": ConstraintType.MFO,  # Mandatory Finish / Finish On
    "CS_MSOA": ConstraintType.SNET,  # Start On or After
    "CS_MSOB": ConstraintType.SNLT,  # Start On or Before
    "CS_MEOA": ConstraintType.FNET,  # Finish On or After
    "CS_MEOB": ConstraintType.FNLT,  # Finish On or Before
}

# P6 TASK.task_type values that are milestones (zero-duration events).
_MILESTONE_TYPES: frozenset[str] = frozenset({"TT_Mile", "TT_FinMile"})


def _parse_tables(xer_text: str) -> dict[str, list[dict[str, str]]]:
    """Parse XER text into ``{table_name: [row-dict, ...]}`` (fields keyed by name)."""
    tables: dict[str, list[dict[str, str]]] = {}
    current_table: str | None = None
    current_fields: list[str] | None = None
    for raw_line in xer_text.splitlines():
        if not raw_line:
            continue
        parts = raw_line.split("\t")
        tag = parts[0]
        if tag == "%T":
            current_table = parts[1].strip() if len(parts) > 1 else None
            current_fields = None
            if current_table is not None:
                tables.setdefault(current_table, [])
        elif tag == "%F":
            current_fields = [f.strip() for f in parts[1:]]
        elif tag == "%R":
            if current_table is None or current_fields is None:
                continue
            values = parts[1:]
            row = {
                field: (values[i] if i < len(values) else "")
                for i, field in enumerate(current_fields)
            }
            tables[current_table].append(row)
        # ERMHDR (header), %E (end), and unknown tags are intentionally ignored.
    return tables


def _require_int(value: str | None, field: str) -> int:
    if value is None or value.strip() == "":
        raise ImporterError(f"XER row is missing required integer {field}")
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ImporterError(f"XER {field} is not an integer: {value!r}") from exc


def _opt_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _hours_to_minutes(value: str | None) -> int:
    """Convert a P6 hours field (e.g. ``"16"`` / ``"7.5"``) to working minutes.

    Preserves sign so lags (which may be negative leads) round-trip correctly.
    A blank or unparseable value is treated as 0.
    """
    if value is None or value.strip() == "":
        return 0
    try:
        return round(float(value.strip()) * 60)
    except ValueError:
        return 0


def _parse_pct(value: str | None) -> float:
    if value is None or value.strip() == "":
        return 0.0
    try:
        return float(value.strip())
    except ValueError:
        return 0.0


def _parse_xer_datetime(value: str | None) -> dt.datetime | None:
    """Parse a P6 datetime (``YYYY-MM-DD HH:MM[:SS]``); blank/sentinel -> None."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    # P6 writes empty dates as a pre-1985 sentinel; treat as absent.
    if parsed.year < 1985:
        return None
    return parsed


def _select_project(
    tables: dict[str, list[dict[str, str]]], task_rows: list[dict[str, str]]
) -> dict[str, str]:
    """Pick the PROJECT row to model: the only one, else the one owning most tasks."""
    projects = tables.get("PROJECT") or []
    if not projects:
        raise ImporterError("XER has no PROJECT table")
    if len(projects) == 1:
        return projects[0]
    counts = Counter(r.get("proj_id", "") for r in task_rows)
    if counts:
        best_proj_id, _ = counts.most_common(1)[0]
        for project in projects:
            if project.get("proj_id") == best_proj_id:
                return project
    return projects[0]


def _build_task(row: dict[str, str]) -> Task:
    task_id = _require_int(row.get("task_id"), "TASK.task_id")
    task_type = (row.get("task_type") or "").strip()
    name = (row.get("task_name") or "").strip() or f"Task {task_id}"
    constraint_code = (row.get("cstr_type") or "").strip()
    return Task(
        unique_id=task_id,
        name=name,
        duration_minutes=_hours_to_minutes(row.get("target_drtn_hr_cnt")),
        is_milestone=task_type in _MILESTONE_TYPES,
        is_summary=task_type == "TT_WBS",
        constraint_type=_CONSTRAINT_BY_XER.get(constraint_code, ConstraintType.ASAP),
        constraint_date=_parse_xer_datetime(row.get("cstr_date")),
        deadline=None,
        percent_complete=_parse_pct(row.get("phys_complete_pct")),
        actual_start=_parse_xer_datetime(row.get("act_start_date")),
        actual_finish=_parse_xer_datetime(row.get("act_end_date")),
        # Forecast finish for CEI: P6 early finish (source-pending -- which P6 field
        # maps to the displayed Finish varies; fixtures assert nothing depending on it).
        finish=_parse_xer_datetime(row.get("early_end_date")),
    )


def _build_relations(tables: dict[str, list[dict[str, str]]]) -> list[Relation]:
    relations: list[Relation] = []
    for row in tables.get("TASKPRED") or []:
        successor_id = _opt_int(row.get("task_id"))
        predecessor_id = _opt_int(row.get("pred_task_id"))
        if successor_id is None or predecessor_id is None:
            continue
        rel_code = (row.get("pred_type") or "").strip()
        relations.append(
            Relation(
                predecessor_id=predecessor_id,
                successor_id=successor_id,
                type=_RELATION_BY_XER.get(rel_code, RelationType.FS),
                lag_minutes=_hours_to_minutes(row.get("lag_hr_cnt")),
            )
        )
    return relations


def parse_xer_string(xer_text: str, *, calendar: Calendar | None = None) -> Schedule:
    """Parse a Primavera P6 XER document (as text) into a :class:`Schedule`."""
    tables = _parse_tables(xer_text)
    if not tables:
        raise ImporterError("not a recognizable XER file (no %T table markers found)")

    task_rows = tables.get("TASK")
    if not task_rows:
        raise ImporterError("XER has no TASK table (or it is empty)")

    project = _select_project(tables, task_rows)
    project_start = _parse_xer_datetime(project.get("plan_start_date"))
    if project_start is None:
        raise ImporterError("XER PROJECT row is missing a usable plan_start_date")

    # Reduce to the selected project's tasks (a Schedule == one project).
    proj_id = (project.get("proj_id") or "").strip()
    if proj_id:
        scoped = [r for r in task_rows if (r.get("proj_id") or "").strip() in ("", proj_id)]
        task_rows = scoped or task_rows

    tasks = [_build_task(row) for row in task_rows]
    task_ids = {task.unique_id for task in tasks}

    # Keep only links whose endpoints are both present (drops cross-project
    # and dangling references), mirroring the MSPDI importer.
    relations = [
        r
        for r in _build_relations(tables)
        if r.predecessor_id in task_ids and r.successor_id in task_ids
    ]

    try:
        return Schedule(
            name=(project.get("proj_short_name") or "").strip() or proj_id or "Untitled",
            project_start=project_start,
            status_date=_parse_xer_datetime(project.get("last_recalc_date")),
            calendar=calendar if calendar is not None else Calendar(),
            tasks=tuple(tasks),
            relations=tuple(relations),
        )
    except pydantic.ValidationError as exc:
        # e.g. a duplicate task_id or a self-referential link in the source data:
        # surface a clean importer error rather than a raw pydantic traceback.
        raise ImporterError(f"XER does not form a valid schedule: {exc}") from exc


def parse_xer(path: str | os.PathLike[str], *, calendar: Calendar | None = None) -> Schedule:
    """Parse a Primavera P6 ``.xer`` file into a :class:`Schedule`.

    XER files are commonly UTF-8 but legacy exports use Windows-1252; we try
    UTF-8 first and fall back to cp1252 so task names survive either encoding.
    """
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return parse_xer_string(text, calendar=calendar)
