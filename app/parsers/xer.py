"""Best-effort importer for Primavera P6 ``.xer`` exports.

XER is a tab-delimited text format: ``%T`` names a table, ``%F`` lists its field names, and each
``%R`` is a row. This parser reads the PROJECT, CALENDAR, TASK and TASKPRED tables with the
standard library only. It is reconstructed from format knowledge (no real sample files were
available when written), so verify the result against your real file — in particular, the
proprietary ``clndr_data`` calendar blob is NOT decoded (calendars fall back to a standard
8h / Mon-Fri / no-holidays calendar). See FIDELITY-COMPROMISE-importers.md.

Mappings: durations/lags are in HOURS (-> minutes x60); ``pred_type`` PR_FS/PR_SS/PR_FF/PR_SF;
constraint codes mapped best-effort (unknown -> ASAP); the project's ``last_recalc_date`` is the
data (status) date.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.models import Calendar, ConstraintType, Relation, RelationType, Schedule, Task

_PRED_TYPE = {
    "PR_FS": RelationType.FS,
    "PR_SS": RelationType.SS,
    "PR_FF": RelationType.FF,
    "PR_SF": RelationType.SF,
}
_CONSTRAINT = {
    "CS_ALAP": ConstraintType.ALAP,
    "CS_MSO": ConstraintType.MSO,
    "CS_MANDSTART": ConstraintType.MSO,
    "CS_MEO": ConstraintType.MFO,
    "CS_MANDFIN": ConstraintType.MFO,
    "CS_MSOA": ConstraintType.SNET,
    "CS_MSOB": ConstraintType.SNLT,
    "CS_MEOA": ConstraintType.FNET,
    "CS_MEOB": ConstraintType.FNLT,
}


def _read_tables(file_path: Path) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    current: str | None = None
    fields: list[str] = []
    raw = file_path.read_text(encoding="cp1252", errors="replace")  # XER is typically Windows-1252
    for line in raw.splitlines():
        parts = line.split("\t")
        tag = parts[0]
        if tag == "%T":
            current = parts[1] if len(parts) > 1 else None
            fields = []
            if current is not None:
                tables[current] = []
        elif tag == "%F":
            fields = parts[1:]
        elif tag == "%R" and current is not None:
            values = parts[1:]
            tables[current].append(
                {field: (values[i] if i < len(values) else "") for i, field in enumerate(fields)}
            )
    return tables


def _date(text: str) -> datetime | None:
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _hours_to_minutes(text: str) -> int:
    try:
        return round(float(text) * 60)
    except ValueError:
        return 0


def _int(text: str, default: int) -> int:
    try:
        return int(float(text))
    except ValueError:
        return default


def parse_xer(file_path: Path) -> Schedule:
    """Parse a Primavera P6 ``.xer`` export into a Schedule (best-effort; see module docstring)."""
    tables = _read_tables(file_path)

    calendars, known_calendars = _build_calendars(tables.get("CALENDAR", []))
    fallback_calendar = calendars[0].calendar_id

    project = tables.get("PROJECT", [{}])[0] if tables.get("PROJECT") else {}
    name = project.get("proj_short_name") or file_path.stem
    project_start = _date(project.get("plan_start_date", "")) or datetime(2000, 1, 1, 8, 0)
    status_date = _date(project.get("last_recalc_date", ""))

    tasks: list[Task] = []
    task_ids: set[int] = set()
    for row in tables.get("TASK", []):
        task_id_text = row.get("task_id", "")
        if not task_id_text:
            continue
        uid = _int(task_id_text, -1)
        if uid < 0 or uid in task_ids:
            continue
        task_ids.add(uid)
        tasks.append(_build_task(row, uid, known_calendars, fallback_calendar))

    relations: list[Relation] = []
    for row in tables.get("TASKPRED", []):
        pred = _int(row.get("pred_task_id", ""), -1)
        succ = _int(row.get("task_id", ""), -1)
        if pred not in task_ids or succ not in task_ids or pred == succ:
            continue
        relations.append(
            Relation(
                predecessor_id=pred,
                successor_id=succ,
                relation_type=_PRED_TYPE.get(row.get("pred_type", ""), RelationType.FS),
                lag_minutes=_hours_to_minutes(row.get("lag_hr_cnt", "")),
            )
        )

    return Schedule(
        name=name,
        project_start=project_start,
        calendars=tuple(calendars),
        tasks=tuple(tasks),
        relations=tuple(relations),
        status_date=status_date,
    )


def _build_calendars(rows: list[dict[str, str]]) -> tuple[list[Calendar], set[int]]:
    calendars: list[Calendar] = []
    seen: set[int] = set()
    for row in rows:
        cid = _int(row.get("clndr_id", ""), -1)
        if cid < 0 or cid in seen:
            continue
        seen.add(cid)
        # clndr_data (working days/holidays) is proprietary and not decoded -> standard defaults.
        calendars.append(
            Calendar(
                calendar_id=cid,
                name=row.get("clndr_name") or f"Calendar {cid}",
                hours_per_day=max(1, _int(row.get("day_hr_cnt", ""), 8)),
            )
        )
    if not calendars:
        calendars.append(Calendar(calendar_id=1, name="Standard", hours_per_day=8))
        seen.add(1)
    return calendars, seen


def _build_task(
    row: dict[str, str], uid: int, known_calendars: set[int], fallback_calendar: int
) -> Task:
    calendar_id = _int(row.get("clndr_id", ""), -1)
    if calendar_id not in known_calendars:
        calendar_id = fallback_calendar

    duration = _hours_to_minutes(row.get("target_drtn_hr_cnt") or row.get("remain_drtn_hr_cnt", ""))
    constraint = _CONSTRAINT.get(row.get("cstr_type", ""), ConstraintType.ASAP)
    constraint_date = _date(row.get("cstr_date", "")) if constraint.needs_date else None
    if constraint.needs_date and constraint_date is None:
        constraint = ConstraintType.ASAP

    actual_start = _date(row.get("act_start_date", ""))
    actual_finish = _date(row.get("act_end_date", ""))
    if actual_finish is not None and actual_start is None:
        actual_start = actual_finish

    return Task(
        unique_id=uid,
        name=row.get("task_name") or row.get("task_code") or f"Task {uid}",
        duration_minutes=max(0, duration),
        calendar_id=calendar_id,
        constraint_type=constraint,
        constraint_date=constraint_date,
        percent_complete=min(100, max(0, _int(row.get("phys_complete_pct", ""), 0))),
        actual_start=actual_start,
        actual_finish=actual_finish,
    )
