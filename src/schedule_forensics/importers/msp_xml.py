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
  * Progress + baseline + resource fields ARE read: ``<PercentComplete>``,
    ``<ActualStart>``/``<ActualFinish>``, the primary baseline (the nested
    ``<Baseline>`` with ``<Number>0</Number>``), and resource assignments
    (``<Resources>`` + ``<Assignments>``). These drive the progress-based DCMA
    checks (Invalid Dates, Resources, Missed Tasks, CPLI, BEI) and earned value;
    without them those metrics SKIP. The primary baseline ``<Cost>`` is read as
    the earned-value budget-at-completion (BAC), so SPI/SPI(t) compute on
    cost-loaded schedules (absent it ``budgeted_cost`` is 0 and they SKIP). This
    matches the COM importer, which reads ``BaselineCost`` into the same field.
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


def _parse_percent(value: str | None) -> float:
    """Parse an MSPDI ``<PercentComplete>`` (integer 0-100) into a float; clamp to range."""
    if value is None:
        return 0.0
    try:
        pct = float(value)
    except ValueError:
        return 0.0
    return min(max(pct, 0.0), 100.0)


def _parse_cost(value: str | None) -> float:
    """Parse an MSPDI ``<Cost>`` (decimal currency units) into a non-negative float.

    MSPDI writes monetary values as decimal currency units directly (no cents
    scaling) -- the same convention the COM importer reads from ``BaselineCost``.
    Absent/blank/unparseable/non-positive -> 0.0, which excludes the task from
    earned value rather than fabricating a budget (LAW 2)."""
    if value is None:
        return 0.0
    try:
        cost = float(value)
    except ValueError:
        return 0.0
    return cost if cost > 0.0 else 0.0


def _parse_baseline(
    task_el: ET.Element,
) -> tuple[dt.datetime | None, dt.datetime | None, float]:
    """Primary baseline (``<Baseline><Number>0</Number>``) Start/Finish/Cost.

    MSPDI nests baselines as ``<Baseline>`` children (a task may carry up to 11,
    numbered 0-10). Baseline 0 is the primary/project baseline that DCMA-11
    (Missed Tasks), BEI, and earned-value PV are measured against; its ``<Cost>``
    is the budget-at-completion (BAC) basis for SPI/SPI(t). Falls back to the
    first ``<Baseline>`` if none is explicitly numbered 0."""
    chosen: ET.Element | None = None
    for bl in task_el.findall("Baseline"):
        if _child_text(bl, "Number") == "0":
            chosen = bl
            break
        if chosen is None:
            chosen = bl
    if chosen is None:
        return None, None, 0.0
    return (
        _parse_datetime(_child_text(chosen, "Start")),
        _parse_datetime(_child_text(chosen, "Finish")),
        _parse_cost(_child_text(chosen, "Cost")),
    )


def _parse_task(task_el: ET.Element, resource_names: tuple[str, ...] = ()) -> Task | None:
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
    baseline_start, baseline_finish, baseline_cost = _parse_baseline(task_el)
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
        percent_complete=_parse_percent(_child_text(task_el, "PercentComplete")),
        actual_start=_parse_datetime(_child_text(task_el, "ActualStart")),
        actual_finish=_parse_datetime(_child_text(task_el, "ActualFinish")),
        baseline_start=baseline_start,
        baseline_finish=baseline_finish,
        budgeted_cost=baseline_cost,
        resource_names=resource_names,
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


def _resource_names_by_task(root: ET.Element) -> dict[int, tuple[str, ...]]:
    """Map task UID -> the names of resources assigned to it (MSPDI Resources + Assignments).

    MSPDI stores resources in a top-level ``<Resources>`` block and task-resource
    assignments in ``<Assignments>`` (each links a ``<TaskUID>`` to a
    ``<ResourceUID>``). DCMA-10 (Resources) needs to know whether an activity is
    resource-loaded, so we resolve each assignment to its resource name. The
    blank/null resource (no ``<Name>``) is skipped, and names are de-duplicated in
    first-seen order."""
    resource_name_by_uid: dict[int, str] = {}
    resources_el = root.find("Resources")
    if resources_el is not None:
        for res_el in resources_el.findall("Resource"):
            uid = _child_text(res_el, "UID")
            name = _child_text(res_el, "Name")
            if uid is not None and name:
                resource_name_by_uid[int(uid)] = name

    names_by_task: dict[int, list[str]] = {}
    assignments_el = root.find("Assignments")
    if assignments_el is not None:
        for assign_el in assignments_el.findall("Assignment"):
            task_uid = _child_text(assign_el, "TaskUID")
            resource_uid = _child_text(assign_el, "ResourceUID")
            if task_uid is None or resource_uid is None:
                continue
            name = resource_name_by_uid.get(int(resource_uid))
            if not name:
                continue
            names = names_by_task.setdefault(int(task_uid), [])
            if name not in names:
                names.append(name)
    return {uid: tuple(names) for uid, names in names_by_task.items()}


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

    resource_names = _resource_names_by_task(root)
    tasks: list[Task] = []
    relations: list[Relation] = []
    tasks_el = root.find("Tasks")
    if tasks_el is not None:
        for task_el in tasks_el.findall("Task"):
            uid_text = _child_text(task_el, "UID")
            names = resource_names.get(int(uid_text), ()) if uid_text is not None else ()
            task = _parse_task(task_el, names)
            if task is None:
                continue
            tasks.append(task)
            relations.extend(_parse_relations(task_el, task.unique_id))

    # Drop links that reference a UID with no corresponding task (defensive).
    task_ids = {t.unique_id for t in tasks}
    relations = [
        r for r in relations if r.predecessor_id in task_ids and r.successor_id in task_ids
    ]

    # Project baseline finish = the latest activity baseline finish (the baselined
    # project completion). MSPDI has no single project-baseline tag; this is the
    # standard rollup and is what CPLI (DCMA-13) indexes the forecast against.
    baseline_finishes = [
        t.baseline_finish for t in tasks if not t.is_summary and t.baseline_finish is not None
    ]
    project_baseline_finish = max(baseline_finishes) if baseline_finishes else None

    try:
        return Schedule(
            # MS Project's <Name> is typically the file name (e.g. "project.xml" from an
            # MPXJ .mpp conversion), while <Title> is the human document title. Prefer
            # the title so the project shows its real name, not the source file name.
            name=_child_text(root, "Title") or _child_text(root, "Name") or "Untitled",
            project_start=project_start,
            status_date=_parse_datetime(_child_text(root, "StatusDate")),
            baseline_finish=project_baseline_finish,
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
