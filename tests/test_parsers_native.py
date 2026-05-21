"""Best-effort native importers — MS Project XML and Primavera XER — against crafted samples,
plus the /upload endpoint. (No real vendor files available; these pin the documented mappings.)"""

from __future__ import annotations

import io
from pathlib import Path

from app import create_app
from app.analysis import analyze_schedule
from app.models import ConstraintType, RelationType
from app.parsers import parse_schedule
from app.parsers.msp_xml import parse_msp_xml
from app.parsers.xer import parse_xer

_MSP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>Imported Project</Name>
  <StartDate>2026-01-05T08:00:00</StartDate>
  <CalendarUID>1</CalendarUID>
  <Calendars>
    <Calendar>
      <UID>1</UID><Name>Standard</Name>
      <WeekDays>
        <WeekDay><DayType>1</DayType><DayWorking>0</DayWorking></WeekDay>
        <WeekDay><DayType>2</DayType><DayWorking>1</DayWorking>
          <WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>16:00:00</ToTime></WorkingTime></WorkingTimes>
        </WeekDay>
        <WeekDay><DayType>3</DayType><DayWorking>1</DayWorking>
          <WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>16:00:00</ToTime></WorkingTime></WorkingTimes>
        </WeekDay>
        <WeekDay><DayType>4</DayType><DayWorking>1</DayWorking>
          <WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>16:00:00</ToTime></WorkingTime></WorkingTimes>
        </WeekDay>
        <WeekDay><DayType>5</DayType><DayWorking>1</DayWorking>
          <WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>16:00:00</ToTime></WorkingTime></WorkingTimes>
        </WeekDay>
        <WeekDay><DayType>6</DayType><DayWorking>1</DayWorking>
          <WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>16:00:00</ToTime></WorkingTime></WorkingTimes>
        </WeekDay>
        <WeekDay><DayType>7</DayType><DayWorking>0</DayWorking></WeekDay>
      </WeekDays>
    </Calendar>
  </Calendars>
  <Resources>
    <Resource><UID>1</UID><Name>Crew</Name></Resource>
  </Resources>
  <Tasks>
    <Task><UID>0</UID><Name>Project Summary</Name><Summary>1</Summary></Task>
    <Task>
      <UID>1</UID><Name>Design</Name><Duration>PT16H0M0S</Duration><CalendarUID>1</CalendarUID>
      <ConstraintType>0</ConstraintType><PercentComplete>0</PercentComplete>
    </Task>
    <Task>
      <UID>2</UID><Name>Build</Name><Duration>PT40H0M0S</Duration><CalendarUID>1</CalendarUID>
      <ConstraintType>4</ConstraintType><ConstraintDate>2026-01-08T08:00:00</ConstraintDate>
      <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type><LinkLag>4800</LinkLag></PredecessorLink>
    </Task>
  </Tasks>
  <Assignments>
    <Assignment><TaskUID>2</TaskUID><ResourceUID>1</ResourceUID></Assignment>
  </Assignments>
</Project>
"""


def test_msp_xml_import(tmp_path: Path) -> None:
    path = tmp_path / "project.xml"
    path.write_text(_MSP_XML)
    schedule = parse_msp_xml(path)

    assert schedule.name == "Imported Project"
    assert {t.unique_id for t in schedule.tasks} == {1, 2}  # UID 0 summary skipped
    cal = schedule.calendars[0]
    assert cal.hours_per_day == 8
    assert cal.working_weekdays == (1, 2, 3, 4, 5)  # MSP Mon..Fri -> ISO 1..5

    build = next(t for t in schedule.tasks if t.unique_id == 2)
    assert build.duration_minutes == 2400  # PT40H
    assert build.constraint_type == ConstraintType.SNET  # code 4
    assert build.resource_names == ("Crew",)

    link = schedule.relations[0]
    assert (link.predecessor_id, link.successor_id) == (1, 2)
    assert link.relation_type == RelationType.FS  # Type 1
    assert link.lag_minutes == 480  # LinkLag 4800 tenths-of-a-minute -> 480 min

    analyze_schedule(schedule)  # the imported schedule is analysable end-to-end


def _xer() -> str:
    rows = [
        ["%T", "PROJECT"],
        ["%F", "proj_id", "proj_short_name", "plan_start_date", "last_recalc_date"],
        ["%R", "1", "DEMO", "2026-01-05 08:00", "2026-01-08 08:00"],
        ["%T", "CALENDAR"],
        ["%F", "clndr_id", "clndr_name", "day_hr_cnt"],
        ["%R", "1", "Standard", "8"],
        ["%T", "TASK"],
        ["%F", "task_id", "task_name", "target_drtn_hr_cnt", "clndr_id", "cstr_type", "cstr_date"],
        ["%R", "100", "Design", "16", "1", "", ""],
        ["%R", "200", "Build", "40", "1", "CS_MSOA", "2026-01-08 08:00"],
        ["%T", "TASKPRED"],
        ["%F", "task_pred_id", "task_id", "pred_task_id", "pred_type", "lag_hr_cnt"],
        ["%R", "1", "200", "100", "PR_FS", "8"],
        ["%E"],
    ]
    return "\n".join("\t".join(row) for row in rows)


def test_xer_import(tmp_path: Path) -> None:
    path = tmp_path / "project.xer"
    path.write_text(_xer(), encoding="cp1252")
    schedule = parse_xer(path)

    assert schedule.name == "DEMO"
    assert {t.unique_id for t in schedule.tasks} == {100, 200}
    design = next(t for t in schedule.tasks if t.unique_id == 100)
    assert design.duration_minutes == 16 * 60  # hours -> minutes
    build = next(t for t in schedule.tasks if t.unique_id == 200)
    assert build.constraint_type == ConstraintType.SNET  # CS_MSOA

    link = schedule.relations[0]
    assert (link.predecessor_id, link.successor_id) == (100, 200)
    assert link.relation_type == RelationType.FS  # PR_FS
    assert link.lag_minutes == 8 * 60

    analyze_schedule(schedule)


def test_parse_schedule_dispatches_by_extension(tmp_path: Path) -> None:
    xml_path = tmp_path / "p.xml"
    xml_path.write_text(_MSP_XML)
    assert parse_schedule(xml_path).name == "Imported Project"


def test_upload_endpoint_imports_xml() -> None:
    client = create_app({"TESTING": True}).test_client()
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(_MSP_XML.encode()), "project.xml")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    schedule = resp.get_json()["schedule"]
    assert {t["unique_id"] for t in schedule["tasks"]} == {1, 2}


def test_upload_endpoint_rejects_mpp() -> None:
    client = create_app({"TESTING": True}).test_client()
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(b"\x00\x01binary"), "plan.mpp")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 415
    assert "Save As" in resp.get_json()["message"]
