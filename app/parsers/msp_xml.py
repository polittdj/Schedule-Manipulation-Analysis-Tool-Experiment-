"""Best-effort importer for MS Project XML (the "File -> Save As -> XML" / MSPDI format).

This is NOT a ``.mpp`` reader — ``.mpp`` is a proprietary binary. This parses the documented
MSPDI XML schema with the Python standard library only. It is reconstructed from format
knowledge (no real sample files were available when it was written), so treat the result as a
starting point and verify it against your real file. See FIDELITY-COMPROMISE-importers.md.

Documented mappings used here:
- Duration: ISO-8601 working time, e.g. ``PT16H0M0S`` -> 960 working minutes.
- PredecessorLink Type: 0=FF, 1=FS, 2=SF, 3=SS.
- LinkLag: stored in TENTHS of a minute, so ``lag_minutes = LinkLag / 10``.
- ConstraintType: 0=ASAP,1=ALAP,2=MSO,3=MFO,4=SNET,5=SNLT,6=FNET,7=FNLT.
- Calendar WeekDay DayType: 1=Sunday..7=Saturday (converted to ISO 1=Mon..7=Sun).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from app.models import Calendar, ConstraintType, Relation, RelationType, Schedule, Task

_LINK_TYPE = {0: RelationType.FF, 1: RelationType.FS, 2: RelationType.SF, 3: RelationType.SS}
_CONSTRAINT = {
    0: ConstraintType.ASAP,
    1: ConstraintType.ALAP,
    2: ConstraintType.MSO,
    3: ConstraintType.MFO,
    4: ConstraintType.SNET,
    5: ConstraintType.SNLT,
    6: ConstraintType.FNET,
    7: ConstraintType.FNLT,
}


def _iso_duration_to_minutes(text: str | None) -> int:
    """``PT16H30M0S`` -> working minutes; 0 if absent/unparseable."""
    if not text:
        return 0
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text.strip())
    if match is None:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 60 + minutes + round(seconds / 60)


def _to_datetime(text: str | None) -> datetime | None:
    if not text or text == "NA":
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _int(text: str | None, default: int) -> int:
    try:
        return int(text) if text is not None else default
    except ValueError:
        return default


def _ns(root: ET.Element) -> str:
    return root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""


def _parse_calendar(calendar_el: ET.Element, q: _Q) -> Calendar:
    uid = _int(calendar_el.findtext(q("UID")), 1)
    name = calendar_el.findtext(q("Name")) or f"Calendar {uid}"
    working_weekdays: list[int] = []
    holidays: list[date] = []
    hours_per_day = 0
    day_start_minute = 480

    weekdays_el = calendar_el.find(q("WeekDays"))
    for weekday in weekdays_el.findall(q("WeekDay")) if weekdays_el is not None else []:
        day_type = _int(weekday.findtext(q("DayType")), 0)
        working = weekday.findtext(q("DayWorking")) == "1"
        if 1 <= day_type <= 7:
            if working:
                working_weekdays.append(7 if day_type == 1 else day_type - 1)  # MSP->ISO
                worked, start = _working_time(weekday, q)
                if worked > hours_per_day:
                    hours_per_day = worked
                    day_start_minute = start
        elif day_type == 0 and not working:  # an exception (non-working) date
            holiday = _to_datetime(_exception_date(weekday, q))
            if holiday is not None:
                holidays.append(holiday.date())

    return Calendar(
        calendar_id=uid,
        name=name,
        hours_per_day=hours_per_day or 8,
        working_weekdays=tuple(working_weekdays) or (1, 2, 3, 4, 5),
        holidays=tuple(sorted(set(holidays))),
        day_start_minute=day_start_minute,
    )


def _working_time(weekday: ET.Element, q: _Q) -> tuple[int, int]:
    """(whole working hours that day, day_start_minute) from <WorkingTimes>."""
    minutes = 0
    start_minute = 480
    times_el = weekday.find(q("WorkingTimes"))
    first = True
    for wt in times_el.findall(q("WorkingTime")) if times_el is not None else []:
        start = _clock_to_minute(wt.findtext(q("FromTime")))
        end = _clock_to_minute(wt.findtext(q("ToTime")))
        if start is not None and end is not None and end > start:
            minutes += end - start
            if first:
                start_minute = start
                first = False
    return minutes // 60, start_minute


def _clock_to_minute(text: str | None) -> int | None:
    if not text:
        return None
    match = re.match(r"(\d{1,2}):(\d{2})", text)
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def _exception_date(weekday: ET.Element, q: _Q) -> str | None:
    period = weekday.find(q("TimePeriod"))
    return period.findtext(q("FromDate")) if period is not None else None


class _Q:
    """Namespace-qualifier: ``q("Task")`` -> ``"{ns}Task"``."""

    def __init__(self, ns: str) -> None:
        self._ns = ns

    def __call__(self, tag: str) -> str:
        return self._ns + tag


def parse_msp_xml(file_path: Path) -> Schedule:
    """Parse an MS Project XML export into a Schedule (best-effort; see module docstring)."""
    root = ET.parse(file_path).getroot()
    q = _Q(_ns(root))

    name = root.findtext(q("Name")) or file_path.stem
    project_start = _to_datetime(root.findtext(q("StartDate"))) or datetime(2000, 1, 1, 8, 0)
    status_date = _to_datetime(root.findtext(q("StatusDate")))
    default_calendar = _int(root.findtext(q("CalendarUID")), 1)

    calendars: list[Calendar] = []
    seen_calendar_ids: set[int] = set()
    calendars_el = root.find(q("Calendars"))
    for cal_el in calendars_el.findall(q("Calendar")) if calendars_el is not None else []:
        calendar = _parse_calendar(cal_el, q)
        if calendar.calendar_id not in seen_calendar_ids:
            seen_calendar_ids.add(calendar.calendar_id)
            calendars.append(calendar)
    if not calendars:
        calendars.append(Calendar(calendar_id=default_calendar, name="Standard", hours_per_day=8))
        seen_calendar_ids.add(default_calendar)
    fallback_calendar = calendars[0].calendar_id

    task_resources = _resource_names_by_task(root, q)

    tasks: list[Task] = []
    relations: list[Relation] = []
    task_ids: set[int] = set()
    tasks_el = root.find(q("Tasks"))
    for task_el in tasks_el.findall(q("Task")) if tasks_el is not None else []:
        uid_text = task_el.findtext(q("UID"))
        if uid_text is None:
            continue
        uid = int(uid_text)
        if uid == 0 or task_el.findtext(q("Summary")) == "1" or uid in task_ids:
            continue  # skip the project summary, summary roll-ups, and duplicates
        task_ids.add(uid)
        tasks.append(
            _build_task(task_el, q, uid, seen_calendar_ids, fallback_calendar, task_resources)
        )
        relations.extend(_build_links(task_el, q, uid))

    relations = [
        r
        for r in relations
        if r.predecessor_id in task_ids
        and r.successor_id in task_ids
        and r.predecessor_id != r.successor_id
    ]

    return Schedule(
        name=name,
        project_start=project_start,
        calendars=tuple(calendars),
        tasks=tuple(tasks),
        relations=tuple(relations),
        status_date=status_date,
    )


def _build_task(
    task_el: ET.Element,
    q: _Q,
    uid: int,
    known_calendars: set[int],
    fallback_calendar: int,
    task_resources: dict[int, list[str]],
) -> Task:
    calendar_id = _int(task_el.findtext(q("CalendarUID")), -1)
    if calendar_id not in known_calendars:
        calendar_id = fallback_calendar

    constraint = _CONSTRAINT.get(
        _int(task_el.findtext(q("ConstraintType")), 0), ConstraintType.ASAP
    )
    constraint_date = (
        _to_datetime(task_el.findtext(q("ConstraintDate"))) if constraint.needs_date else None
    )
    if constraint.needs_date and constraint_date is None:
        constraint = ConstraintType.ASAP  # defensive: a dated constraint with no usable date

    actual_start = _to_datetime(task_el.findtext(q("ActualStart")))
    actual_finish = _to_datetime(task_el.findtext(q("ActualFinish")))
    if actual_finish is not None and actual_start is None:
        actual_start = actual_finish  # our model requires a start if there is a finish

    baseline_finish: datetime | None = None
    for baseline in task_el.findall(q("Baseline")):
        if (baseline.findtext(q("Number")) or "0") == "0":
            baseline_finish = _to_datetime(baseline.findtext(q("Finish")))
            break

    return Task(
        unique_id=uid,
        name=task_el.findtext(q("Name")) or f"Task {uid}",
        duration_minutes=max(0, _iso_duration_to_minutes(task_el.findtext(q("Duration")))),
        calendar_id=calendar_id,
        constraint_type=constraint,
        constraint_date=constraint_date,
        deadline=_to_datetime(task_el.findtext(q("Deadline"))),
        percent_complete=min(100, max(0, _int(task_el.findtext(q("PercentComplete")), 0))),
        actual_start=actual_start,
        actual_finish=actual_finish,
        baseline_finish=baseline_finish,
        resource_names=tuple(task_resources.get(uid, ())),
    )


def _build_links(task_el: ET.Element, q: _Q, uid: int) -> list[Relation]:
    links: list[Relation] = []
    for link in task_el.findall(q("PredecessorLink")):
        pred_text = link.findtext(q("PredecessorUID"))
        if pred_text is None:
            continue
        links.append(
            Relation(
                predecessor_id=int(pred_text),
                successor_id=uid,
                relation_type=_LINK_TYPE.get(_int(link.findtext(q("Type")), 1), RelationType.FS),
                lag_minutes=round(_int(link.findtext(q("LinkLag")), 0) / 10),  # tenths of a minute
            )
        )
    return links


def _resource_names_by_task(root: ET.Element, q: _Q) -> dict[int, list[str]]:
    names: dict[int, str] = {}
    resources_el = root.find(q("Resources"))
    for resource in resources_el.findall(q("Resource")) if resources_el is not None else []:
        ruid = resource.findtext(q("UID"))
        rname = resource.findtext(q("Name"))
        if ruid is not None and rname:
            names[int(ruid)] = rname

    by_task: dict[int, list[str]] = {}
    assignments_el = root.find(q("Assignments"))
    for assignment in assignments_el.findall(q("Assignment")) if assignments_el is not None else []:
        task_uid = assignment.findtext(q("TaskUID"))
        resource_uid = assignment.findtext(q("ResourceUID"))
        if task_uid is None or resource_uid is None:
            continue
        rname = names.get(int(resource_uid))
        if rname:
            by_task.setdefault(int(task_uid), []).append(rname)
    return by_task
