"""Post-M5 integration: analyze_schedule + the /analyze endpoint (M1+M2+M4+M5 end-to-end)."""

from __future__ import annotations

from datetime import datetime

from app import create_app
from app.analysis import analyze_schedule
from app.models import RelationType, Severity
from tests.conftest import make_relation, make_schedule, make_task

DAY = 480


def _chain(n: int) -> object:
    # Tasks carry a resource so Metric 10 passes; no status_date/baseline, so progress
    # metrics 9 and 11 are (correctly) skipped.
    tasks = tuple(
        make_task(i, duration_minutes=DAY, resource_names=("crew",)) for i in range(1, n + 1)
    )
    relations = tuple(make_relation(i, i + 1) for i in range(1, n))
    return make_schedule(tasks=tasks, relations=relations)


def test_analyze_schedule_composes_cpm_and_metrics() -> None:
    report = analyze_schedule(_chain(3))
    assert report.project_finish_minutes == 3 * DAY
    assert report.project_finish_working_days == 3.0
    assert report.critical_path == (1, 2, 3)
    assert {m.metric_id for m in report.metrics} == {1, 2, 3, 4, 5, 6, 7, 8, 10, 12}
    # 9/11/13/14 need status-date / baseline data this schedule lacks.
    assert {s.metric_id for s in report.skipped_metrics} == {9, 11, 13, 14}
    by_id = {m.metric_id: m for m in report.metrics}
    assert by_id[4].severity == Severity.PASS  # 100% FS
    assert by_id[2].severity == Severity.PASS  # no leads
    assert by_id[3].severity == Severity.PASS  # no lags
    assert by_id[6].severity == Severity.PASS  # short tasks
    assert by_id[7].severity == Severity.PASS  # all critical, no float
    assert by_id[10].severity == Severity.PASS  # every task has a resource


def test_report_includes_per_task_timings() -> None:
    report = analyze_schedule(_chain(3))
    assert len(report.timings) == 3
    tasks = {t["unique_id"]: t for t in report.to_dict()["tasks"]}
    assert tasks[1]["early_start_minutes"] == 0
    assert tasks[3]["early_finish_minutes"] == 3 * DAY
    assert tasks[1]["total_slack_working_days"] == 0.0
    assert all(t["is_critical"] for t in tasks.values())  # pure chain -> all critical


def test_analyze_endpoint_returns_report() -> None:
    schedule = _chain(2)
    client = create_app({"TESTING": True}).test_client()
    resp = client.post("/analyze", data=schedule.model_dump_json(), content_type="application/json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project_finish_working_days"] == 2.0
    assert body["critical_path"] == [1, 2]
    assert {m["metric_id"] for m in body["metrics"]} == {1, 2, 3, 4, 5, 6, 7, 8, 10, 12}


def test_analyze_endpoint_rejects_invalid_schedule() -> None:
    client = create_app({"TESTING": True}).test_client()
    resp = client.post("/analyze", data=b'{"not": "a schedule"}', content_type="application/json")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_schedule"


def test_analyze_endpoint_cyclic_schedule_returns_422() -> None:
    tasks = (make_task(1), make_task(2))
    schedule = make_schedule(tasks=tasks, relations=(make_relation(1, 2), make_relation(2, 1)))
    client = create_app({"TESTING": True}).test_client()
    resp = client.post("/analyze", data=schedule.model_dump_json(), content_type="application/json")
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "cpm_error"


def test_analyze_skips_unrunnable_metrics_without_fabricating() -> None:
    # one task, no relations / no progress data: relation-based 2/3/4 and progress 9/11 are
    # skipped (not faked PASS); the rest run.
    schedule = make_schedule(tasks=(make_task(1, duration_minutes=DAY),), relations=())
    report = analyze_schedule(schedule)
    assert {m.metric_id for m in report.metrics} == {1, 5, 6, 7, 8, 10, 12}
    assert {s.metric_id for s in report.skipped_metrics} == {2, 3, 4, 9, 11, 13, 14}


def _fully_tracked_schedule() -> object:
    # A 3-task FS chain (durations 2/5/3 days) with resources, progress, baselines and a data
    # date 3 working days in, so every one of the 14 metrics has the data it needs to run.
    tasks = (
        make_task(
            1,
            duration_minutes=2 * DAY,
            resource_names=("crew",),
            percent_complete=100,
            actual_start=datetime(2026, 1, 5, 8, 0),
            actual_finish=datetime(2026, 1, 6, 16, 0),  # on its baseline
            baseline_finish=datetime(2026, 1, 6, 16, 0),  # due (<= data date)
        ),
        make_task(
            2,
            duration_minutes=5 * DAY,
            resource_names=("crew",),
            baseline_finish=datetime(2026, 1, 16, 16, 0),
        ),
        make_task(
            3,
            duration_minutes=3 * DAY,
            resource_names=("crew",),
            baseline_finish=datetime(2026, 1, 22, 16, 0),
        ),
    )
    relations = (make_relation(1, 2), make_relation(2, 3))
    return make_schedule(
        tasks=tasks,
        relations=relations,
        status_date=datetime(2026, 1, 8, 8, 0),  # 3 working days in
        baseline_finish=datetime(2026, 1, 16, 16, 0),  # == forecast finish (10 working days)
    )


def test_all_fourteen_metrics_run_end_to_end() -> None:
    report = analyze_schedule(_fully_tracked_schedule())
    assert {m.metric_id for m in report.metrics} == set(range(1, 15))
    assert report.skipped_metrics == ()  # every metric had the data it needed
    by_id = {m.metric_id: m for m in report.metrics}
    assert by_id[13].measured == 1.0  # CPLI: baseline == forecast
    assert by_id[13].severity == Severity.PASS
    assert by_id[14].severity == Severity.PASS  # the one due task completed on time
    assert by_id[12].severity == Severity.PASS  # delay propagates through the chain


def test_analyze_flags_non_fs_relation() -> None:
    tasks = (make_task(1), make_task(2), make_task(3))
    relations = (
        make_relation(1, 2),
        make_relation(2, 3, relation_type=RelationType.SS),
    )  # 1 FS of 2 == 50% FS -> Metric 4 FAIL
    report = analyze_schedule(make_schedule(tasks=tasks, relations=relations))
    by_id = {m.metric_id: m for m in report.metrics}
    assert by_id[4].severity == Severity.FAIL
    assert by_id[4].offenders[0].unique_id == 3  # successor of the SS tie
