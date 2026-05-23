"""Native ``.mpp`` importer via MS Project COM automation -- OPTIONAL, WINDOWS-ONLY.

This is an optional Windows-only enhancement behind the importer interface; it is
NEVER the only path (Commandment 1). The cross-platform primary path is MS Project
XML + Primavera XER (pure-Python) + native ``.mpp`` via MPXJ-as-subprocess. COM
cannot run on Linux/macOS, so this module is designed so the *mapping* is testable
off-Windows while only the live connection is Windows-bound:

  * :func:`schedule_from_com_project` is a PURE function. It takes a duck-typed COM
    project object (anything exposing ``.Name``/``.StatusDate``/``.ProjectStart``/
    ``.Tasks`` ...) and builds a :class:`Schedule`. It imports NO ``win32com`` and
    does no I/O, so it is exercised on Linux with a FAKE COM object (see
    ``tests/test_com_msproject.py``). This is the same split MS Project's own
    object model exposes; only the connection is platform-bound.
  * :func:`parse_mpp_via_com` is the WINDOWS-ONLY driver. The ``win32com`` /
    ``pythoncom`` imports live INSIDE the function so this module imports cleanly
    on every platform; off-Windows the guard raises :class:`ComUnavailableError`.

Fidelity / fragility notes (LAW 2; cite CLAUDE.md "Windows / COM gotchas"):
  * Gotcha 4: the ``Tasks`` collection has ``None`` entries (blank rows) -- skipped.
  * Gotcha 5: COM ``Duration``/``LinkLag``/slack are in MINUTES (480 == one 8-hr
    day). We read ``.Duration`` as minutes directly (no scaling). SOURCE-PENDING:
    the minute unit and any per-task-calendar effect on day<->minute display are
    asserted against a fixture here and MUST be verified against the live MS
    Project object model on Windows (see docs/HAZARDS.md, H-NO-COM-HERE).
  * Gotcha 6: ``StatusDate`` (and other dates) may be ``"NA"`` or a pre-1985
    sentinel -- both normalize to ``None``.
  * Gotcha 9: COM dates are normalized to ISO ``datetime`` immediately.
  * Gotcha 10 (SOURCE-PENDING): the ConstraintType / Dependency.Type integer
    enumerations below follow the documented MS Project codes, but versions vary
    -- VERIFY against the live object model on Windows before trusting them. These
    match the MSPDI codes in ``importers/msp_xml.py`` (single source of truth for
    the code->enum maps would be ideal; kept consistent here by inspection).
  * Resources are read defensively from ``Task.Resources`` (or ``ResourceNames``);
    cost from ``Task.Cost`` if present. All accessors tolerate ``None``
    (Commandment 5).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
from pathlib import Path
from typing import Any

import pydantic

from schedule_forensics.schemas import (
    Calendar,
    ConstraintType,
    Relation,
    RelationType,
    Schedule,
    Task,
)


class ComUnavailableError(RuntimeError):
    """Raised when MS Project COM automation cannot be used (e.g. off-Windows)."""


class ComImporterError(ValueError):
    """Raised when a live COM project cannot be mapped into a :class:`Schedule`."""


# MS Project ConstraintType codes. SOURCE-PENDING (CLAUDE.md gotcha 10): verify
# against the live object model on Windows -- versions vary. Matches the MSPDI
# codes in importers/msp_xml.py.
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

# MS Project Dependency.Type codes. SOURCE-PENDING (CLAUDE.md gotcha 10).
_RELATION_BY_CODE: dict[int, RelationType] = {
    0: RelationType.FF,
    1: RelationType.FS,
    2: RelationType.SF,
    3: RelationType.SS,
}

# MS Project writes "no date" as a pre-1985 sentinel; treat anything older as absent.
_DATE_SENTINEL_YEAR = 1985


def _getattr_or_none(obj: object, name: str) -> Any:
    """Read ``obj.name`` defensively. COM accessors can be absent or raise.

    Any missing attribute or COM error (raised lazily on access) normalizes to
    ``None`` so a single odd field can never abort the whole import (Commandment 5).
    """
    try:
        return getattr(obj, name, None)
    except Exception:  # noqa: BLE001 -- a flaky COM property must not crash the import.
        return None


def _to_datetime(value: Any) -> dt.datetime | None:
    """Normalize a COM date value to an ISO ``datetime`` (gotcha 9), or ``None``.

    Handles the MS Project ``"NA"`` string and the pre-1985 sentinel (gotcha 6),
    pywin32 ``pywintypes.datetime`` (a ``datetime`` subclass), naive/aware
    ``datetime``, ``date``, and ISO strings. Anything unrecognized -> ``None``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.upper() == "NA":
            return None
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        return None if parsed.year < _DATE_SENTINEL_YEAR else parsed
    # pywintypes.datetime subclasses datetime, so this catches the COM case too.
    if isinstance(value, dt.datetime):
        naive = value.replace(tzinfo=None) if value.tzinfo is not None else value
        return None if naive.year < _DATE_SENTINEL_YEAR else naive
    if isinstance(value, dt.date):
        if value.year < _DATE_SENTINEL_YEAR:
            return None
        return dt.datetime(value.year, value.month, value.day)
    return None


def _to_int_minutes(value: Any) -> int:
    """Coerce a COM duration/lag (minutes -- gotcha 5) to a non-negative int.

    ``None`` and unparseable values become 0. SOURCE-PENDING: the minute unit is
    the documented COM convention but is verified against a fixture, not the live
    object model, on Linux.
    """
    if value is None:
        return 0  # absent duration -> 0
    try:
        minutes = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return minutes if minutes > 0 else 0


def _to_lag_minutes(value: Any) -> int:
    """Coerce a COM dependency lag (minutes -- gotcha 5) to int; a lead is negative."""
    if value is None:
        return 0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _to_percent(value: Any) -> float:
    """Coerce a COM PercentComplete to a float clamped to [0, 100] (Commandment 5)."""
    if value is None:
        return 0.0
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pct < 0.0:
        return 0.0
    if pct > 100.0:
        return 100.0
    return pct


def _to_cost(value: Any) -> float:
    """Coerce a COM cost to a non-negative float (schema requires ge=0)."""
    if value is None:
        return 0.0
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return 0.0
    return cost if cost > 0.0 else 0.0


def _to_bool(value: Any) -> bool:
    """Coerce a COM boolean-ish flag to ``bool`` (``None`` -> ``False``)."""
    return bool(value)


def _constraint_from_code(value: Any) -> ConstraintType:
    """Map a COM ConstraintType code to the enum; unknown/absent -> ASAP."""
    if value is None:
        return ConstraintType.ASAP
    try:
        code = int(value)
    except (TypeError, ValueError):
        return ConstraintType.ASAP
    return _CONSTRAINT_BY_CODE.get(code, ConstraintType.ASAP)


def _relation_from_code(value: Any) -> RelationType:
    """Map a COM Dependency.Type code to the enum; unknown/absent -> FS."""
    if value is None:
        return RelationType.FS
    try:
        code = int(value)
    except (TypeError, ValueError):
        return RelationType.FS
    return _RELATION_BY_CODE.get(code, RelationType.FS)


def _resource_names(task: object) -> tuple[str, ...]:
    """Read resource names from a COM task, tolerating several shapes (Commandment 5).

    Prefers iterating ``task.Resources`` (a collection of resources each with a
    ``.Name``); falls back to the semicolon-delimited ``task.ResourceNames``
    string. Returns an empty tuple when neither is present.
    """
    resources = _getattr_or_none(task, "Resources")
    names: list[str] = []
    if resources is not None:
        try:
            for res in resources:
                if res is None:
                    continue
                name = _getattr_or_none(res, "Name")
                if name:
                    names.append(str(name))
        except TypeError:
            names = []  # not iterable -> fall through to the string form
    if not names:
        joined = _getattr_or_none(task, "ResourceNames")
        if joined:
            names = [part.strip() for part in str(joined).split(";") if part.strip()]
    return tuple(names)


def _map_task(task: object) -> Task | None:
    """Map one COM task object to a :class:`Task`, or ``None`` to skip it.

    Returns ``None`` for a blank-row entry (no ``UniqueID``); the caller also
    skips the ``None`` collection entries themselves (gotcha 4).
    """
    uid_raw = _getattr_or_none(task, "UniqueID")
    if uid_raw is None:
        return None
    try:
        uid = int(uid_raw)
    except (TypeError, ValueError):
        return None

    name_raw = _getattr_or_none(task, "Name")
    name = str(name_raw) if name_raw not in (None, "") else f"Task {uid}"

    return Task(
        unique_id=uid,
        name=name,
        duration_minutes=_to_int_minutes(_getattr_or_none(task, "Duration")),
        is_milestone=_to_bool(_getattr_or_none(task, "Milestone")),
        is_summary=_to_bool(_getattr_or_none(task, "Summary")),
        constraint_type=_constraint_from_code(_getattr_or_none(task, "ConstraintType")),
        constraint_date=_to_datetime(_getattr_or_none(task, "ConstraintDate")),
        deadline=_to_datetime(_getattr_or_none(task, "Deadline")),
        percent_complete=_to_percent(_getattr_or_none(task, "PercentComplete")),
        actual_start=_to_datetime(_getattr_or_none(task, "ActualStart")),
        actual_finish=_to_datetime(_getattr_or_none(task, "ActualFinish")),
        finish=_to_datetime(_getattr_or_none(task, "Finish")),  # forecast finish (CEI)
        baseline_start=_to_datetime(_getattr_or_none(task, "BaselineStart")),
        baseline_finish=_to_datetime(_getattr_or_none(task, "BaselineFinish")),
        budgeted_cost=_to_cost(_getattr_or_none(task, "BaselineCost")),
        resource_names=_resource_names(task),
    )


def _map_relations(task: object, successor_id: int) -> list[Relation]:
    """Map a COM task's predecessor links into :class:`Relation` objects.

    Reads ``task.TaskDependencies`` (each dependency exposes ``.From``/``.To``
    tasks with a ``.UniqueID``, a ``.Type`` code, and a ``.Lag`` in minutes), only
    keeping dependencies where THIS task is the successor (the ``To`` side) so each
    link is emitted exactly once across the project. Tolerates ``None`` entries
    and missing attributes (Commandment 5).
    """
    relations: list[Relation] = []
    deps = _getattr_or_none(task, "TaskDependencies")
    if deps is None:
        return relations
    try:
        iterator = iter(deps)
    except TypeError:
        return relations
    for dep in iterator:
        if dep is None:
            continue
        to_task = _getattr_or_none(dep, "To")
        to_uid_raw = _getattr_or_none(to_task, "UniqueID") if to_task is not None else None
        # Only emit the link when this task is the successor, to avoid duplicates
        # (each dependency appears on both the predecessor and successor task).
        if to_uid_raw is None:
            continue
        try:
            to_uid = int(to_uid_raw)
        except (TypeError, ValueError):
            continue
        if to_uid != successor_id:
            continue
        from_task = _getattr_or_none(dep, "From")
        from_uid_raw = _getattr_or_none(from_task, "UniqueID") if from_task is not None else None
        if from_uid_raw is None:
            continue
        try:
            pred_uid = int(from_uid_raw)
        except (TypeError, ValueError):
            continue
        if pred_uid == successor_id:
            continue  # self-link; the schema would reject it anyway
        relations.append(
            Relation(
                predecessor_id=pred_uid,
                successor_id=successor_id,
                type=_relation_from_code(_getattr_or_none(dep, "Type")),
                lag_minutes=_to_lag_minutes(_getattr_or_none(dep, "Lag")),
            )
        )
    return relations


def schedule_from_com_project(project: object, *, calendar: Calendar | None = None) -> Schedule:
    """Map a (duck-typed) MS Project COM project object into a :class:`Schedule`.

    PURE FUNCTION -- imports no ``win32com`` and performs no I/O, so it is fully
    unit-testable off-Windows with a fake COM object. The live ``parse_mpp_via_com``
    driver passes ``app.ActiveProject`` here.

    Reads ``project.Name``, the project start (``ProjectStart`` then ``Start``),
    ``project.StatusDate`` and ``project.BaselineFinish``, and iterates
    ``project.Tasks`` (skipping ``None`` blank rows -- gotcha 4), mapping each task
    and its predecessor links. Every accessor tolerates ``None`` (Commandment 5).
    """
    name_raw = _getattr_or_none(project, "Name")
    name = str(name_raw) if name_raw not in (None, "") else "Untitled"

    # Project start: MS Project exposes ProjectStart; some object models use Start.
    project_start = _to_datetime(_getattr_or_none(project, "ProjectStart"))
    if project_start is None:
        project_start = _to_datetime(_getattr_or_none(project, "Start"))
    if project_start is None:
        raise ComImporterError(
            "COM project has no usable ProjectStart/Start date (cannot anchor the schedule)"
        )

    tasks: list[Task] = []
    relations: list[Relation] = []
    com_tasks = _getattr_or_none(project, "Tasks")
    if com_tasks is not None:
        try:
            iterator = iter(com_tasks)
        except TypeError as exc:
            raise ComImporterError("COM project.Tasks is not iterable") from exc
        for com_task in iterator:
            if com_task is None:
                continue  # blank-row entry (gotcha 4)
            task = _map_task(com_task)
            if task is None:
                continue
            tasks.append(task)
            relations.extend(_map_relations(com_task, task.unique_id))

    # Drop links referencing a UID with no corresponding task (defensive parity
    # with the MSPDI importer).
    task_ids = {t.unique_id for t in tasks}
    relations = [
        r for r in relations if r.predecessor_id in task_ids and r.successor_id in task_ids
    ]

    try:
        return Schedule(
            name=name,
            project_start=project_start,
            status_date=_to_datetime(_getattr_or_none(project, "StatusDate")),
            baseline_finish=_to_datetime(_getattr_or_none(project, "BaselineFinish")),
            calendar=calendar if calendar is not None else Calendar(),
            tasks=tuple(tasks),
            relations=tuple(relations),
        )
    except pydantic.ValidationError as exc:
        raise ComImporterError(f"COM project does not form a valid schedule: {exc}") from exc


def parse_mpp_via_com(
    path: str | os.PathLike[str], *, calendar: Calendar | None = None
) -> Schedule:
    """Open a native ``.mpp`` via MS Project COM and map it (WINDOWS-ONLY).

    Off-Windows (no ``win32com``/``pythoncom``) this raises
    :class:`ComUnavailableError`. On Windows it initializes COM, starts MS Project
    HEADLESS (``Visible=False``/``DisplayAlerts=False`` set BEFORE any open --
    gotcha 2), opens ``path`` (absolute, ``ReadOnly=True`` -- gotcha 7), maps the
    active project, and ALWAYS tears the app down in ``finally`` so a failure can't
    leave a zombie ``MSPROJECT.EXE`` (gotcha 8). COM is single-threaded; callers
    must read files sequentially (H-COM-SINGLE-THREAD).

    This path CANNOT be exercised on Linux (that's expected); the pure mapping in
    :func:`schedule_from_com_project` is what the test suite verifies here.
    """
    try:
        import pythoncom  # noqa: PLC0415 -- Windows-only; guarded (mypy override silences missing import)
        import win32com.client  # noqa: PLC0415 -- Windows-only; import inside fn keeps module portable
    except ImportError as exc:
        raise ComUnavailableError(
            "COM requires Windows + pywin32 + MS Project (win32com/pythoncom not importable). "
            "Use the cross-platform importers (MS Project XML / Primavera XER / MPXJ) instead."
        ) from exc

    abspath = os.path.abspath(os.fspath(path))
    if not Path(abspath).is_file():
        raise ComImporterError(f"input file does not exist: {abspath}")

    pythoncom.CoInitialize()
    app: Any = None
    opened = False
    try:
        app = win32com.client.Dispatch("MSProject.Application")
        # Headless BEFORE opening anything (gotcha 2 / Commandment 6).
        app.Visible = False
        app.DisplayAlerts = False
        # Absolute path, READ-ONLY (gotcha 7): never lock or risk modifying the
        # source .mpp. FileOpenEx(Name, ReadOnly, ...) -> the 2nd positional is
        # ReadOnly, so it must be True.
        app.FileOpenEx(abspath, True)
        opened = True
        project = app.ActiveProject
        if project is None:
            raise ComImporterError(f"MS Project opened {abspath} but exposed no ActiveProject")
        return schedule_from_com_project(project, calendar=calendar)
    finally:
        # Tear down defensively so no single failure leaves a zombie MSPROJECT.EXE
        # (gotcha 8). Each step is independently suppressed so a failure in one
        # cleanup step never skips the next (or the CoUninitialize).
        if app is not None:
            if opened:
                with contextlib.suppress(Exception):
                    app.FileCloseEx(0, False)  # pjDoNotSave, no save-as
            with contextlib.suppress(Exception):
                app.Quit()
        pythoncom.CoUninitialize()
