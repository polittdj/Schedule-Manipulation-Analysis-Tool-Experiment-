"""Post-M5 integration: analyze_schedule + the /analyze endpoint (M1+M2+M4+M5 end-to-end)."""

from __future__ import annotations

from app import create_app
from app.analysis import analyze_schedule
from app.models import RelationType, Severity
from tests.conftest import make_relation, make_schedule, make_task

DAY = 480


def _chain(n: int) -> object:
    tasks = tuple(make_task(i, duration_minutes=DAY) for i in range(1, n + 1))
    relations = tuple(make_relation(i, i + 1) for i in range(1, n))
    return make_schedule(tasks=tasks, relations=relations)


def test_analyze_schedule_composes_cpm_and_metrics() -> None:
    report = analyze_schedule(_chain(3))
    assert report.project_finish_minutes == 3 * DAY
    assert report.project_finish_working_days == 3.0
    assert report.critical_path == (1, 2, 3)
    assert len(report.metrics) == 4
    assert report.skipped_metrics == ()
    by_id = {m.metric_id: m for m in report.metrics}
    assert by_id[4].severity == Severity.PASS  # 100% FS
    assert by_id[2].severity == Severity.PASS  # no leads
    assert by_id[3].severity == Severity.PASS  # no lags


def test_analyze_endpoint_returns_report() -> None:
    schedule = _chain(2)
    client = create_app({"TESTING": True}).test_client()
    resp = client.post("/analyze", data=schedule.model_dump_json(), content_type="application/json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project_finish_working_days"] == 2.0
    assert body["critical_path"] == [1, 2]
    assert len(body["metrics"]) == 4
    assert {m["metric_id"] for m in body["metrics"]} == {1, 2, 3, 4}


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
    # one task, no relations: CPM runs; metrics 2/3/4 have no relations -> skipped (not faked PASS).
    schedule = make_schedule(tasks=(make_task(1, duration_minutes=DAY),), relations=())
    report = analyze_schedule(schedule)
    assert [m.metric_id for m in report.metrics] == [1]
    assert {s.metric_id for s in report.skipped_metrics} == {2, 3, 4}


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
