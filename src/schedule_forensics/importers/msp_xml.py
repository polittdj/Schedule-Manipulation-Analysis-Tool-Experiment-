"""MS Project XML (MSPDI) importer -- pure-Python, deterministic, no network I/O.

This is the primary, Linux-testable ingestion path. It reads the schema MS
Project writes via *File -> Save As -> XML* (the ``http://schemas.microsoft.com/
project`` namespace).

Fidelity notes (LAW 2):
  * ``<Duration>`` is ISO-8601 (e.g. ``PT16H0M0S``). MS Project encodes *working*
    hours in the span, so the total minutes of the span ARE working minutes
    (16h == 960 working minutes == 2 days at 480/day). Calendar-day-encoded
    durations would need calendar-aware conversion -- deferred (docs/HAZARDS.md).
  * ConstraintType / PredecessorLink Type integer codes follow the MS Project
    enumeration (see ``_CONSTRAINT_BY_CODE`` / ``_RELATION_BY_CODE``).
  * ``<LinkLag>`` unit (tenths-of-a-minute assumption) is SOURCE-PENDING and is
    therefore not relied upon by the golden fixtures (their lags are 0). See
    docs/HAZARDS.md (H-MSPDI-LAG-UNIT).
  * The MSPDI ``<Calendars>`` block is not yet parsed; the default
    ``Calendar`` (480 min/day, Mon-Fri) is used. Deferred.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import xml.etree.ElementTree as ET
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
    """Raised when an MSPDI document cannot be parsed into a Schedule."""


# MS Project ConstraintType codes (MSPDI / COM share these values).
_CONSTRAINT_BY_CODE: dict[int, ConstraintType] = {
    0: ConstraintType.ASAP,
    1: ConstraintType.ALAP,
    2: ConstraintType.MSO,
    3: ConstraintType.MFO,
    4: ConstraintType.SNET,
    5: ConstraintType.SNLT,
    6: ConstraintType.FNET,
    7: ConstraintType.FNLT,
}

# MSPDI PredecessorLink Type codes.
_RELATION_BY_CODE: dict[int, RelationType] = {
    0: RelationType.FF,
    1: RelationType.FS,
    2: RelationType.SF,
    3: RelationType.SS,
}

_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def _strip_namespaces(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _child_text(parent: ET.Element, tag: str) -> str | None:
    el = parent.find(tag)
    if el is None or el.text is None:
        return None
    text = el.text.strip()
    return text or None


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if value is None:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    # MS Project writes NA/empty dates as a pre-1985 sentinel; treat as absent.
    if parsed.year < 1985:
        return None
    return parsed


def iso_duration_to_minutes(value: str) -> int:
    """Convert an ISO-8601 duration (as MSPDI writes it) to working minutes."""
    match = _ISO_DURATION.match(value.strip())
    if match is None:
        raise ImporterError(f"unparseable ISO-8601 duration: {value!r}")
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 24 * 60 + hours * 60 + minutes + seconds // 60


def _link_lag_to_minutes(link_lag: str | None) -> int:
    # SOURCE-PENDING: MSPDI LinkLag is assumed to be tenths of a minute.
    if link_lag is None:
        return 0
    try:
        return round(int(link_lag) / 10)
    except ValueError:
        return 0


def _parse_task(task_el: ET.Element) -> Task | None:
    uid_text = _child_text(task_el, "UID")
    if uid_text is None:
        return None  # structural / blank row
    uid = int(uid_text)
    duration_text = _child_text(task_el, "Duration")
    duration_minutes = iso_duration_to_minutes(duration_text) if duration_text else 0
    is_summary = _child_text(task_el, "Summary") == "1" or uid == 0
    constraint_code = _child_text(task_el, "ConstraintType")
    constraint_type = ConstraintType.ASAP
    if constraint_code is not None:
        constraint_type = _CONSTRAINT_BY_CODE.get(int(constraint_code), ConstraintType.ASAP)
    return Task(
        unique_id=uid,
        name=_child_text(task_el, "Name") or f"Task {uid}",
        duration_minutes=duration_minutes,
        is_milestone=_child_text(task_el, "Milestone") == "1",
        is_summary=is_summary,
        constraint_type=constraint_type,
        constraint_date=_parse_datetime(_child_text(task_el, "ConstraintDate")),
        deadline=_parse_datetime(_child_text(task_el, "Deadline")),
        finish=_parse_datetime(_child_text(task_el, "Finish")),  # forecast finish (CEI)
        actual_finish=_parse_datetime(_child_text(task_el, "ActualFinish")),
    )


def _parse_relations(task_el: ET.Element, successor_id: int) -> list[Relation]:
    relations: list[Relation] = []
    for link in task_el.findall("PredecessorLink"):
        pred_text = _child_text(link, "PredecessorUID")
        if pred_text is None:
            continue
        type_code = _child_text(link, "Type")
        rel_type = (
            _RELATION_BY_CODE.get(int(type_code), RelationType.FS)
            if type_code is not None
            else RelationType.FS
        )
        relations.append(
            Relation(
                predecessor_id=int(pred_text),
                successor_id=successor_id,
                type=rel_type,
                lag_minutes=_link_lag_to_minutes(_child_text(link, "LinkLag")),
            )
        )
    return relations


def parse_msp_xml_string(xml_text: str, *, calendar: Calendar | None = None) -> Schedule:
    """Parse an MSPDI XML document (as text) into a :class:`Schedule`."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ImporterError(f"not well-formed XML: {exc}") from exc
    _strip_namespaces(root)
    if root.tag != "Project":
        raise ImporterError(f"root element is <{root.tag}>, expected <Project> (MSPDI)")

    project_start = _parse_datetime(_child_text(root, "StartDate"))
    if project_start is None:
        raise ImporterError("MSPDI <Project> is missing a usable <StartDate>")

    tasks: list[Task] = []
    relations: list[Relation] = []
    tasks_el = root.find("Tasks")
    if tasks_el is not None:
        for task_el in tasks_el.findall("Task"):
            task = _parse_task(task_el)
            if task is None:
                continue
            tasks.append(task)
            relations.extend(_parse_relations(task_el, task.unique_id))

    # Drop links that reference a UID with no corresponding task (defensive).
    task_ids = {t.unique_id for t in tasks}
    relations = [
        r for r in relations if r.predecessor_id in task_ids and r.successor_id in task_ids
    ]

    try:
        return Schedule(
            # MS Project's <Name> is typically the file name (e.g. "project.xml" from an
            # MPXJ .mpp conversion), while <Title> is the human document title. Prefer
            # the title so the project shows its real name, not the source file name.
            name=_child_text(root, "Title") or _child_text(root, "Name") or "Untitled",
            project_start=project_start,
            status_date=_parse_datetime(_child_text(root, "StatusDate")),
            calendar=calendar if calendar is not None else Calendar(),
            tasks=tuple(tasks),
            relations=tuple(relations),
        )
    except pydantic.ValidationError as exc:
        # e.g. a duplicate UID in the source: surface a clean importer error
        # rather than a raw pydantic traceback (the UI shows this verbatim).
        raise ImporterError(f"MSPDI does not form a valid schedule: {exc}") from exc


def parse_msp_xml(path: str | os.PathLike[str], *, calendar: Calendar | None = None) -> Schedule:
    """Parse an MSPDI XML file into a :class:`Schedule`."""
    xml_text = Path(path).read_text(encoding="utf-8")
    return parse_msp_xml_string(xml_text, calendar=calendar)
