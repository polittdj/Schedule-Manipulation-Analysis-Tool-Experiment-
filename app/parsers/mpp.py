"""MS Project ``.mpp`` reader via MPXJ.

``.mpp`` is a proprietary binary OLE compound document; the robust, industry-standard way to read
it is the MPXJ Java library through its ``mpxj`` Python bindings (which bridge to a JVM via JPype).
MPXJ's ``UniversalProjectReader`` reads ``.mpp`` (all MS Project versions), ``.xer``, ``.mpx`` and
MSPDI ``.xml``.

This is an **optional capability**: it needs Java 17+ on the machine and ``pip install mpxj``
(see ``requirements-mpp.txt``). If either is missing, ``parse_mpp`` raises ``NotImplementedError``
with guidance — including the universal fallback: in MS Project, *File → Save As → XML* and load
that ``.xml`` (which this tool reads with no Java).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import Calendar, ConstraintType, Relation, RelationType, Schedule, Task

_UNAVAILABLE_MESSAGE = (
    ".mpp is MS Project's proprietary binary format. To read it here, install Java 17+ and run "
    "'pip install mpxj' (the MPXJ library). The no-setup alternative: in MS Project use "
    "File -> Save As -> XML and load that .xml file (Primavera .xer also works)."
)

# MPXJ ConstraintType enum name -> our ConstraintType.
_CONSTRAINT = {
    "AS_SOON_AS_POSSIBLE": ConstraintType.ASAP,
    "AS_LATE_AS_POSSIBLE": ConstraintType.ALAP,
    "MUST_START_ON": ConstraintType.MSO,
    "MUST_FINISH_ON": ConstraintType.MFO,
    "START_NO_EARLIER_THAN": ConstraintType.SNET,
    "START_NO_LATER_THAN": ConstraintType.SNLT,
    "FINISH_NO_EARLIER_THAN": ConstraintType.FNET,
    "FINISH_NO_LATER_THAN": ConstraintType.FNLT,
}
# MPXJ RelationType enum name -> our RelationType (MPXJ already uses FS/SS/FF/SF).
_RELATION = {
    "FS": RelationType.FS,
    "SS": RelationType.SS,
    "FF": RelationType.FF,
    "SF": RelationType.SF,
}


def _ensure_mpxj() -> Any:
    """Import mpxj and start the JVM, or raise NotImplementedError with guidance."""
    try:
        import mpxj  # type: ignore
    except ImportError as exc:
        raise NotImplementedError(_UNAVAILABLE_MESSAGE) from exc
    if not mpxj.isJVMStarted():
        try:
            mpxj.startJVM()
        except Exception as exc:  # no/!broken Java runtime
            raise NotImplementedError(_UNAVAILABLE_MESSAGE) from exc
    return mpxj


def parse_mpp(file_path: Path) -> Schedule:
    """Parse an MS Project ``.mpp`` (or any MPXJ-readable file) into a Schedule via MPXJ."""
    _ensure_mpxj()
    from org.mpxj import TimeUnit  # type: ignore
    from org.mpxj.reader import UniversalProjectReader  # type: ignore

    project = UniversalProjectReader().read(str(file_path))
    if project is None:
        raise NotImplementedError(_UNAVAILABLE_MESSAGE)
    return _to_schedule(project, TimeUnit, file_path.stem)


def _to_schedule(project: Any, time_unit: Any, default_name: str) -> Schedule:
    props = project.getProjectProperties()
    minutes = time_unit.MINUTES

    calendars, known_calendars, fallback_calendar = _build_calendars(project, props)

    tasks: list[Task] = []
    relations: list[Relation] = []
    task_ids: set[int] = set()
    for mpxj_task in project.getTasks():
        if mpxj_task is None:
            continue
        uid = mpxj_task.getUniqueID()
        if uid is None or int(uid) == 0 or bool(mpxj_task.getSummary()) or int(uid) in task_ids:
            continue
        uid = int(uid)
        task_ids.add(uid)
        tasks.append(
            _build_task(mpxj_task, uid, props, minutes, known_calendars, fallback_calendar)
        )
        relations.extend(_build_relations(mpxj_task, uid, props, minutes))

    relations = [
        r
        for r in relations
        if r.predecessor_id in task_ids
        and r.successor_id in task_ids
        and r.predecessor_id != r.successor_id
    ]

    return Schedule(
        name=str(props.getName() or default_name),
        project_start=_to_datetime(props.getStartDate()) or datetime(2000, 1, 1, 8, 0),
        calendars=tuple(calendars),
        tasks=tuple(tasks),
        relations=tuple(relations),
        status_date=_to_datetime(props.getStatusDate()),
    )


def _build_calendars(project: Any, props: Any) -> tuple[list[Calendar], set[int], int]:
    hours_per_day = max(1, round((props.getMinutesPerDay() or 480) / 60))
    calendars: list[Calendar] = []
    seen: set[int] = set()
    for index, mpxj_cal in enumerate(project.getCalendars() or []):
        if mpxj_cal is None:
            continue
        raw_uid = mpxj_cal.getUniqueID()
        uid = int(raw_uid) if raw_uid is not None else index + 1
        if uid in seen:
            continue
        seen.add(uid)
        # Working days/holidays of MPXJ calendars are not mapped (best-effort) — durations are
        # still converted faithfully via the project's minutes-per-day.
        calendars.append(
            Calendar(
                calendar_id=uid,
                name=str(mpxj_cal.getName() or f"Calendar {uid}"),
                hours_per_day=hours_per_day,
            )
        )
    if not calendars:
        calendars.append(Calendar(calendar_id=1, name="Standard", hours_per_day=hours_per_day))
        seen.add(1)
    return calendars, seen, calendars[0].calendar_id


def _build_task(
    mpxj_task: Any,
    uid: int,
    props: Any,
    minutes: Any,
    known_calendars: set[int],
    fallback_calendar: int,
) -> Task:
    calendar = mpxj_task.getCalendar()
    calendar_id = (
        int(calendar.getUniqueID())
        if calendar is not None and calendar.getUniqueID() is not None
        else fallback_calendar
    )
    if calendar_id not in known_calendars:
        calendar_id = fallback_calendar

    constraint = _CONSTRAINT.get(str(mpxj_task.getConstraintType()), ConstraintType.ASAP)
    constraint_date = _to_datetime(mpxj_task.getConstraintDate()) if constraint.needs_date else None
    if constraint.needs_date and constraint_date is None:
        constraint = ConstraintType.ASAP

    actual_start = _to_datetime(mpxj_task.getActualStart())
    actual_finish = _to_datetime(mpxj_task.getActualFinish())
    if actual_finish is not None and actual_start is None:
        actual_start = actual_finish

    return Task(
        unique_id=uid,
        name=str(mpxj_task.getName() or f"Task {uid}"),
        duration_minutes=_duration_minutes(mpxj_task.getDuration(), props, minutes),
        calendar_id=calendar_id,
        constraint_type=constraint,
        constraint_date=constraint_date,
        deadline=_to_datetime(mpxj_task.getDeadline()),
        percent_complete=min(100, max(0, _to_int(mpxj_task.getPercentageComplete()))),
        actual_start=actual_start,
        actual_finish=actual_finish,
        baseline_finish=_to_datetime(mpxj_task.getBaselineFinish()),
        resource_names=_resource_names(mpxj_task),
    )


def _build_relations(mpxj_task: Any, uid: int, props: Any, minutes: Any) -> list[Relation]:
    relations: list[Relation] = []
    for link in mpxj_task.getPredecessors() or []:
        predecessor = link.getPredecessorTask()
        if predecessor is None or predecessor.getUniqueID() is None:
            continue
        relations.append(
            Relation(
                predecessor_id=int(predecessor.getUniqueID()),
                successor_id=uid,
                relation_type=_RELATION.get(str(link.getType()), RelationType.FS),
                lag_minutes=_duration_minutes(link.getLag(), props, minutes),
            )
        )
    return relations


def _resource_names(mpxj_task: Any) -> tuple[str, ...]:
    names: list[str] = []
    for assignment in mpxj_task.getResourceAssignments() or []:
        resource = assignment.getResource()
        if resource is not None and resource.getName():
            names.append(str(resource.getName()))
    return tuple(names)


def _duration_minutes(duration: Any, props: Any, minutes: Any) -> int:
    if duration is None:
        return 0
    value = duration.convertUnits(minutes, props).getDuration()
    return max(0, round(float(value)))


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(float(str(value)))
    except ValueError:
        return 0
