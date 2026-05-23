"""Primavera P6 XER importer tests: field parity, helpers, edge cases, mutation.

Non-vacuous discipline (H-VACUOUS-TEST): the mutation test FAILS if the duration
field is not actually read; the cross-importer test asserts the XER and MSPDI
paths produce the SAME network from equivalent inputs (Law 2 parity).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from schedule_forensics.importers.msp_xml import parse_msp_xml
from schedule_forensics.importers.xer import ImporterError, parse_xer, parse_xer_string
from schedule_forensics.schemas import ConstraintType, RelationType, Schedule

FIXTURE = Path(__file__).parent / "fixtures" / "xer" / "simple_network.xer"
MSP_FIXTURE = Path(__file__).parent / "fixtures" / "msp_xml" / "simple_network.xml"


# ── Inline XER builders (real tabs; keyed by field name) ──────────────────────


def _table(name: str, fields: list[str], rows: list[list[str]]) -> str:
    out = [f"%T\t{name}", "%F\t" + "\t".join(fields)]
    out.extend("%R\t" + "\t".join(r) for r in rows)
    return "\n".join(out)


def _xer_doc(*sections: str) -> str:
    return "ERMHDR\t8.4\n" + "\n".join(sections) + "\n%E\n"


_PROJECT_FIELDS = ["proj_id", "proj_short_name", "plan_start_date"]
_TASK_FIELDS = ["task_id", "proj_id", "task_name", "task_type", "target_drtn_hr_cnt"]


# ── Fixture field parity ──────────────────────────────────────────────────────


def test_parse_fixture_fields() -> None:
    schedule = parse_xer(FIXTURE)
    assert schedule.name == "SAMPLE-A"
    assert schedule.project_start == dt.datetime(2025, 1, 6, 8)
    assert schedule.status_date == dt.datetime(2025, 1, 20, 17)
    assert len(schedule.tasks) == 4

    by_id = {task.unique_id: task for task in schedule.tasks}
    assert by_id[1].name == "A - Foundation"
    assert by_id[1].duration_minutes == 960  # 16h x 60
    assert by_id[1].is_milestone is False
    assert by_id[2].duration_minutes == 1440  # 24h x 60
    assert by_id[4].is_milestone is True  # TT_FinMile
    assert by_id[4].duration_minutes == 0
    assert all(task.constraint_type is ConstraintType.ASAP for task in schedule.tasks)


def test_parse_fixture_relations() -> None:
    schedule = parse_xer(FIXTURE)
    edges = {(r.predecessor_id, r.successor_id, r.type, r.lag_minutes) for r in schedule.relations}
    assert edges == {
        (1, 2, RelationType.FS, 0),
        (1, 3, RelationType.FS, 0),
        (2, 4, RelationType.FS, 0),
        (3, 4, RelationType.FS, 0),
    }


def test_cross_importer_equivalence_with_mspdi() -> None:
    """The XER and MSPDI fixtures describe the same network -> equivalent Schedules."""
    xer = parse_xer(FIXTURE)
    msp = parse_msp_xml(MSP_FIXTURE)
    assert xer.project_start == msp.project_start
    assert xer.status_date == msp.status_date

    def shape(s: Schedule) -> dict[int, tuple[str, int, bool]]:
        return {t.unique_id: (t.name, t.duration_minutes, t.is_milestone) for t in s.tasks}

    assert shape(xer) == shape(msp)
    xer_edges = {(r.predecessor_id, r.successor_id, r.type, r.lag_minutes) for r in xer.relations}
    msp_edges = {(r.predecessor_id, r.successor_id, r.type, r.lag_minutes) for r in msp.relations}
    assert xer_edges == msp_edges


def test_string_and_file_paths_agree() -> None:
    from_file = parse_xer(FIXTURE)
    from_string = parse_xer_string(FIXTURE.read_text(encoding="utf-8"))
    assert from_file == from_string


# ── Mapping helpers ───────────────────────────────────────────────────────────


def test_relation_types_ff_sf_map() -> None:
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table(
            "TASK",
            _TASK_FIELDS,
            [
                ["1", "1", "A", "TT_Task", "8"],
                ["2", "1", "B", "TT_Task", "8"],
                ["3", "1", "C", "TT_Task", "8"],
            ],
        ),
        _table(
            "TASKPRED",
            ["task_id", "pred_task_id", "pred_type", "lag_hr_cnt"],
            [["2", "1", "PR_FF", "0"], ["3", "1", "PR_SF", "0"]],
        ),
    )
    by_pair = {(r.predecessor_id, r.successor_id): r.type for r in parse_xer_string(doc).relations}
    assert by_pair[(1, 2)] is RelationType.FF
    assert by_pair[(1, 3)] is RelationType.SF


def test_lag_hours_to_minutes_including_lead() -> None:
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table(
            "TASK",
            _TASK_FIELDS,
            [
                ["1", "1", "A", "TT_Task", "8"],
                ["2", "1", "B", "TT_Task", "8"],
                ["3", "1", "C", "TT_Task", "8"],
            ],
        ),
        _table(
            "TASKPRED",
            ["task_id", "pred_task_id", "pred_type", "lag_hr_cnt"],
            [["2", "1", "PR_FS", "2"], ["3", "1", "PR_SS", "-1"]],  # +2h lag; -1h lead
        ),
    )
    edges = {
        (r.predecessor_id, r.successor_id, r.type, r.lag_minutes)
        for r in parse_xer_string(doc).relations
    }
    assert (1, 2, RelationType.FS, 120) in edges
    assert (1, 3, RelationType.SS, -60) in edges


def test_constraint_codes_map() -> None:
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table(
            "TASK",
            ["task_id", "proj_id", "task_name", "task_type", "target_drtn_hr_cnt", "cstr_type"],
            [
                ["1", "1", "X", "TT_Task", "8", "CS_MSOB"],
                ["2", "1", "Y", "TT_Task", "8", "CS_ALAP"],
            ],
        ),
    )
    by_id = {t.unique_id: t for t in parse_xer_string(doc).tasks}
    assert by_id[1].constraint_type is ConstraintType.SNLT  # Start On or Before
    assert by_id[2].constraint_type is ConstraintType.ALAP


def test_fields_read_by_name_not_position() -> None:
    # Columns deliberately shuffled; the parser must key off the %F names.
    doc = _xer_doc(
        _table(
            "PROJECT",
            ["plan_start_date", "proj_short_name", "proj_id"],
            [["2025-01-06 08:00", "P", "1"]],
        ),
        _table(
            "TASK",
            ["task_type", "target_drtn_hr_cnt", "task_name", "proj_id", "task_id"],
            [["TT_Task", "8", "Only Task", "1", "7"]],
        ),
    )
    tasks = parse_xer_string(doc).tasks
    assert len(tasks) == 1
    assert tasks[0].unique_id == 7
    assert tasks[0].name == "Only Task"
    assert tasks[0].duration_minutes == 480


def test_multi_project_reduces_to_majority_and_drops_cross_links() -> None:
    doc = _xer_doc(
        _table(
            "PROJECT",
            _PROJECT_FIELDS,
            [["1", "MAIN", "2025-01-06 08:00"], ["2", "OTHER", "2025-02-01 08:00"]],
        ),
        _table(
            "TASK",
            _TASK_FIELDS,
            [
                ["1", "1", "A", "TT_Task", "8"],
                ["2", "1", "B", "TT_Task", "8"],
                ["3", "1", "C", "TT_Task", "8"],
                ["99", "2", "Z (other project)", "TT_Task", "8"],
            ],
        ),
        _table(
            "TASKPRED",
            ["task_id", "pred_task_id", "pred_type", "lag_hr_cnt"],
            [["2", "1", "PR_FS", "0"], ["99", "2", "PR_FS", "0"]],  # 2nd link is cross-project
        ),
    )
    schedule = parse_xer_string(doc)
    assert schedule.name == "MAIN"  # majority project (3 tasks vs 1)
    assert {t.unique_id for t in schedule.tasks} == {1, 2, 3}  # project-2 task excluded
    assert {(r.predecessor_id, r.successor_id) for r in schedule.relations} == {(1, 2)}


# ── Mutation discipline (the field is actually read) ──────────────────────────


def test_duration_mutation_is_actually_read() -> None:
    original = FIXTURE.read_text(encoding="utf-8")
    mutated = original.replace("\tTT_Task\t16\t", "\tTT_Task\t8\t")
    assert mutated != original  # guard: the mutation actually applied
    by_id = {t.unique_id: t.duration_minutes for t in parse_xer_string(mutated).tasks}
    assert by_id[1] == 480  # was 960 (16h); now 8h


# ── Edge cases (fail closed; never a silently-empty schedule) ─────────────────


def test_missing_task_table_raises() -> None:
    doc = _xer_doc(_table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]))
    with pytest.raises(ImporterError):
        parse_xer_string(doc)


def test_missing_project_raises() -> None:
    doc = _xer_doc(_table("TASK", _TASK_FIELDS, [["1", "1", "A", "TT_Task", "8"]]))
    with pytest.raises(ImporterError):
        parse_xer_string(doc)


def test_missing_plan_start_date_raises() -> None:
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", ""]]),
        _table("TASK", _TASK_FIELDS, [["1", "1", "A", "TT_Task", "8"]]),
    )
    with pytest.raises(ImporterError):
        parse_xer_string(doc)


def test_garbage_is_rejected() -> None:
    with pytest.raises(ImporterError):
        parse_xer_string("this is not an XER file\njust prose, no record tags\n")


# ── Hardening: real-world edge cases ──────────────────────────────────────────


def test_duplicate_task_id_raises_importer_error() -> None:
    # A duplicate task_id must surface as a clean ImporterError, not a raw
    # pydantic ValidationError (clean importer contract / better UI message).
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table(
            "TASK",
            _TASK_FIELDS,
            [["1", "1", "A", "TT_Task", "8"], ["1", "1", "B", "TT_Task", "8"]],
        ),
    )
    with pytest.raises(ImporterError):
        parse_xer_string(doc)


def test_crlf_line_endings_parse() -> None:
    # Real P6 exports use Windows CRLF line endings; the parser must handle them.
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table("TASK", _TASK_FIELDS, [["1", "1", "A - Foundation", "TT_Task", "8"]]),
    ).replace("\n", "\r\n")
    tasks = parse_xer_string(doc).tasks
    assert len(tasks) == 1
    assert tasks[0].name == "A - Foundation"  # no stray trailing \r in the value


def test_fractional_duration_hours() -> None:
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table("TASK", _TASK_FIELDS, [["1", "1", "A", "TT_Task", "7.5"]]),
    )
    assert parse_xer_string(doc).tasks[0].duration_minutes == 450  # 7.5h x 60


def test_short_row_pads_missing_trailing_fields() -> None:
    # A %R row with fewer values than %F fields: missing trailing fields are blank,
    # not an error (duration -> 0, constraint -> ASAP).
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table(
            "TASK",
            ["task_id", "proj_id", "task_name", "task_type", "target_drtn_hr_cnt", "cstr_type"],
            [["1", "1", "A", "TT_Task"]],  # missing duration + cstr_type
        ),
    )
    task = parse_xer_string(doc).tasks[0]
    assert task.duration_minutes == 0
    assert task.constraint_type is ConstraintType.ASAP


def test_early_end_date_maps_to_finish() -> None:
    # P6 early_end_date -> Task.finish (forecast finish, for CEI; source-pending mapping).
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table(
            "TASK",
            [
                "task_id",
                "proj_id",
                "task_name",
                "task_type",
                "target_drtn_hr_cnt",
                "early_end_date",
            ],
            [["1", "1", "A", "TT_Task", "8", "2025-02-15 17:00"]],
        ),
    )
    assert parse_xer_string(doc).tasks[0].finish == dt.datetime(2025, 2, 15, 17)


def test_start_milestone_type_is_milestone() -> None:
    doc = _xer_doc(
        _table("PROJECT", _PROJECT_FIELDS, [["1", "P", "2025-01-06 08:00"]]),
        _table("TASK", _TASK_FIELDS, [["1", "1", "Kickoff", "TT_Mile", "0"]]),
    )
    assert parse_xer_string(doc).tasks[0].is_milestone is True
