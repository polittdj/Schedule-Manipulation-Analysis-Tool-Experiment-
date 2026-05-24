"""MS Project XML importer tests: field-by-field parity against a synthetic fixture."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from schedule_forensics.importers.msp_xml import (
    ImporterError,
    iso_duration_to_minutes,
    parse_msp_xml,
    parse_msp_xml_string,
)
from schedule_forensics.schemas import ConstraintType, RelationType

FIXTURE = Path(__file__).parent / "fixtures" / "msp_xml" / "simple_network.xml"


def test_iso_duration_to_minutes() -> None:
    assert iso_duration_to_minutes("PT16H0M0S") == 960
    assert iso_duration_to_minutes("PT0H0M0S") == 0
    assert iso_duration_to_minutes("PT8H30M0S") == 510
    with pytest.raises(ImporterError):
        iso_duration_to_minutes("garbage")


def test_parse_fixture_fields() -> None:
    schedule = parse_msp_xml(FIXTURE)
    assert schedule.name == "Forensic Sample A"
    assert schedule.project_start == dt.datetime(2025, 1, 6, 8)
    assert schedule.status_date == dt.datetime(2025, 1, 20, 17)
    assert len(schedule.tasks) == 4

    by_id = {task.unique_id: task for task in schedule.tasks}
    assert by_id[1].name == "A - Foundation"
    assert by_id[1].duration_minutes == 960
    assert by_id[1].is_milestone is False
    assert by_id[4].is_milestone is True
    assert by_id[4].duration_minutes == 0
    assert all(task.constraint_type is ConstraintType.ASAP for task in schedule.tasks)


def _minimal_mspdi(*, name: str | None, title: str | None) -> str:
    name_el = f"<Name>{name}</Name>" if name is not None else ""
    title_el = f"<Title>{title}</Title>" if title is not None else ""
    return (
        '<Project xmlns="http://schemas.microsoft.com/project">'
        f"{name_el}{title_el}"
        "<StartDate>2026-03-02T08:00:00</StartDate>"
        "<Tasks><Task><UID>1</UID><Name>A</Name><Duration>PT8H0M0S</Duration></Task></Tasks>"
        "</Project>"
    )


def test_project_name_prefers_title_over_filename_name() -> None:
    # MPXJ writes the source file name into <Name> (e.g. "project.xml") and the real
    # project title into <Title>; the human title must win.
    schedule = parse_msp_xml_string(
        _minimal_mspdi(name="project.xml", title="Commercial Construction")
    )
    assert schedule.name == "Commercial Construction"


def test_project_name_falls_back_to_name_then_untitled() -> None:
    assert parse_msp_xml_string(_minimal_mspdi(name="Only Name", title=None)).name == "Only Name"
    assert parse_msp_xml_string(_minimal_mspdi(name=None, title=None)).name == "Untitled"


def test_parse_fixture_relations() -> None:
    schedule = parse_msp_xml(FIXTURE)
    edges = {(r.predecessor_id, r.successor_id, r.type, r.lag_minutes) for r in schedule.relations}
    assert edges == {
        (1, 2, RelationType.FS, 0),
        (1, 3, RelationType.FS, 0),
        (2, 4, RelationType.FS, 0),
        (3, 4, RelationType.FS, 0),
    }


def test_namespace_stripped_and_constraint_code_maps() -> None:
    xml = (
        '<?xml version="1.0"?>'
        '<Project xmlns="http://schemas.microsoft.com/project">'
        "<Name>NS Test</Name><StartDate>2025-01-06T08:00:00</StartDate>"
        "<Tasks><Task><UID>1</UID><Name>X</Name><Duration>PT8H0M0S</Duration>"
        "<ConstraintType>5</ConstraintType></Task></Tasks></Project>"
    )
    schedule = parse_msp_xml_string(xml)
    assert schedule.tasks[0].constraint_type is ConstraintType.SNLT
    assert schedule.tasks[0].duration_minutes == 480


def test_missing_start_date_raises() -> None:
    xml = (
        '<Project xmlns="http://schemas.microsoft.com/project">'
        "<Name>x</Name><Tasks></Tasks></Project>"
    )
    with pytest.raises(ImporterError):
        parse_msp_xml_string(xml)


def test_not_well_formed_xml_raises() -> None:
    with pytest.raises(ImporterError):
        parse_msp_xml_string("<Project><unclosed>")


def test_duplicate_uid_raises_importer_error() -> None:
    # Two tasks with the same UID must surface as a clean ImporterError, not a raw
    # pydantic ValidationError (the UI renders the message verbatim).
    xml = (
        '<Project xmlns="http://schemas.microsoft.com/project">'
        "<Name>dup</Name><StartDate>2025-01-06T08:00:00</StartDate>"
        "<Tasks>"
        "<Task><UID>1</UID><Name>A</Name><Duration>PT8H0M0S</Duration></Task>"
        "<Task><UID>1</UID><Name>B</Name><Duration>PT8H0M0S</Duration></Task>"
        "</Tasks></Project>"
    )
    with pytest.raises(ImporterError):
        parse_msp_xml_string(xml)


def test_finish_and_actual_finish_are_read() -> None:
    # Forecast finish (for CEI) and actual finish are read from MSPDI.
    xml = (
        '<Project xmlns="http://schemas.microsoft.com/project">'
        "<Name>x</Name><StartDate>2025-01-06T08:00:00</StartDate>"
        "<Tasks><Task><UID>1</UID><Name>A</Name><Duration>PT8H0M0S</Duration>"
        "<Finish>2025-02-15T17:00:00</Finish>"
        "<ActualFinish>2025-02-10T17:00:00</ActualFinish></Task></Tasks></Project>"
    )
    task = parse_msp_xml_string(xml).tasks[0]
    assert task.finish == dt.datetime(2025, 2, 15, 17)
    assert task.actual_finish == dt.datetime(2025, 2, 10, 17)


def test_duration_mutation_is_actually_read() -> None:
    # Mutation discipline: editing the XML duration changes the parsed value,
    # proving the importer reads the field rather than returning a constant.
    mutated = FIXTURE.read_text(encoding="utf-8").replace("PT16H0M0S", "PT8H0M0S")
    schedule = parse_msp_xml_string(mutated)
    by_id = {task.unique_id: task.duration_minutes for task in schedule.tasks}
    assert by_id[1] == 480
