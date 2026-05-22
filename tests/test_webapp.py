"""Tests for the Schedule Forensics Flask web UI.

All tests use Flask's test client (no real server started).
State is reset between tests via the ``reset_state`` fixture so tests are
independent of each other.

LAW 1 checks verified here:
  - HOST == "127.0.0.1" (module-level constant).
  - No schedule data leaves the machine (all routes operate in-memory; tested
    by verifying that after /wipe the analysis state is gone).

Tests are non-vacuous: each assertion checks a specific value, not merely
"response is truthy" (H-VACUOUS-TEST mitigation).
"""

from __future__ import annotations

import datetime as dt
import io
import json
from collections.abc import Generator
from pathlib import Path

import pytest

from schedule_forensics.report_excel import CUI_NOTICE
from schedule_forensics.schemas import Relation, Schedule, Task
from schedule_forensics.webapp import DEFAULT_PORT, HOST, PORT_ENV_VAR, create_app, resolve_port
from schedule_forensics.webapp.app import _STATE, _clear_state

# ── Fixtures ──────────────────────────────────────────────────────────────────

_FIXTURE_XML = Path(__file__).parent / "fixtures" / "msp_xml" / "simple_network.xml"

_START = dt.datetime(2025, 1, 6, 8, 0, 0)


def _minimal_schedule() -> Schedule:
    """Build a minimal two-task schedule that analysis can process."""
    return Schedule(
        name="UI Test Schedule",
        project_start=_START,
        status_date=_START,
        tasks=(
            Task(unique_id=1, name="Alpha", duration_minutes=960),
            Task(unique_id=2, name="Beta", duration_minutes=480),
        ),
        relations=(Relation(predecessor_id=1, successor_id=2),),
    )


@pytest.fixture(autouse=True)
def reset_state() -> Generator[None, None, None]:
    """Clear in-memory state before and after every test (test isolation)."""
    _clear_state()
    yield
    _clear_state()


@pytest.fixture()
def client() -> Generator[object, None, None]:
    """Return a Flask test client with TESTING=True."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── LAW 1 constant check ──────────────────────────────────────────────────────


def test_host_constant_is_loopback() -> None:
    """LAW 1: the server MUST bind to 127.0.0.1 only."""
    assert HOST == "127.0.0.1"


# ── Port resolution (--port > SF_PORT > default; fail closed on bad input) ────


def test_resolve_port_default_when_unset() -> None:
    """No CLI arg and no env var → default port 5000."""
    assert resolve_port(None, {}) == DEFAULT_PORT
    assert DEFAULT_PORT == 5000


def test_resolve_port_env_var_used_when_no_cli() -> None:
    """SF_PORT is honoured when --port is absent."""
    assert resolve_port(None, {PORT_ENV_VAR: "5050"}) == 5050


def test_resolve_port_cli_overrides_env() -> None:
    """--port takes precedence over SF_PORT (explicit beats environment)."""
    assert resolve_port(8080, {PORT_ENV_VAR: "5050"}) == 8080


def test_resolve_port_blank_env_falls_back_to_default() -> None:
    """An empty/whitespace SF_PORT is treated as unset, not as an error."""
    assert resolve_port(None, {PORT_ENV_VAR: "   "}) == DEFAULT_PORT


def test_resolve_port_non_integer_env_fails_closed() -> None:
    """A non-integer SF_PORT raises rather than silently using the default (fail closed)."""
    with pytest.raises(ValueError, match=PORT_ENV_VAR):
        resolve_port(None, {PORT_ENV_VAR: "not-a-port"})


def test_resolve_port_out_of_range_fails_closed() -> None:
    """Ports outside 1..65535 raise rather than being clamped (fail closed)."""
    with pytest.raises(ValueError, match="1..65535"):
        resolve_port(70000, {})
    with pytest.raises(ValueError, match="1..65535"):
        resolve_port(0, {})
    with pytest.raises(ValueError, match="1..65535"):
        resolve_port(None, {PORT_ENV_VAR: "99999"})


# ── Basic route smoke tests ───────────────────────────────────────────────────


def test_index_200_contains_cui_notice(client: object) -> None:
    """GET / returns 200 and the CUI notice is visible."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    # CUI_NOTICE is the single source of truth; the banner must contain its text.
    assert CUI_NOTICE in body


def test_health_endpoint(client: object) -> None:
    """GET /health returns 200 JSON {"status":"ok"}."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.get("/health")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload == {"status": "ok"}


# ── /analyze with valid JSON ──────────────────────────────────────────────────


def test_analyze_json_returns_dashboard(client: object) -> None:
    """POST /analyze with a valid JSON schedule returns 200 with health band and finish."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    sched = _minimal_schedule()
    resp = c.post(
        "/analyze",
        data={"json_text": sched.model_dump_json()},
    )
    assert resp.status_code == 200
    body = resp.data.decode()
    # Must render a health band (GREEN / YELLOW / RED)
    assert any(band in body for band in ("GREEN", "YELLOW", "RED"))
    # Must render the project-finish value (1440 working minutes for 960+480 FS chain)
    assert "1440" in body


def test_analyze_json_stores_state(client: object) -> None:
    """After POST /analyze with JSON, _STATE holds the analysis."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    sched = _minimal_schedule()
    c.post("/analyze", data={"json_text": sched.model_dump_json()})
    assert _STATE["analysis"] is not None
    assert _STATE["schedule"] is not None


def test_dashboard_renders_earned_value_section(client: object) -> None:
    """The dashboard shows the earned-value indices (SKIPPED for a non-EV schedule)."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.post("/analyze", data={"json_text": _minimal_schedule().model_dump_json()})
    body = resp.data.decode()
    assert "Earned-Value Indices" in body
    assert "SPI(t)" in body
    assert "SKIPPED" in body  # no budget/baseline data -> never fabricated


def test_dashboard_renders_earned_value_number(client: object) -> None:
    """With earned-value data, the dashboard shows the computed SPI (0.7500)."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    d7, d8 = dt.datetime(2025, 1, 7, 8), dt.datetime(2025, 1, 8, 8)
    sched = Schedule(
        name="EV UI",
        project_start=_START,
        status_date=d8,
        tasks=(
            Task(
                unique_id=1,
                name="A",
                duration_minutes=480,
                percent_complete=100.0,
                baseline_start=_START,
                baseline_finish=d7,
                budgeted_cost=100.0,
            ),
            Task(
                unique_id=2,
                name="B",
                duration_minutes=480,
                percent_complete=50.0,
                baseline_start=d7,
                baseline_finish=d8,
                budgeted_cost=100.0,
            ),
        ),
    )
    resp = c.post("/analyze", data={"json_text": sched.model_dump_json()})
    body = resp.data.decode()
    assert "0.7500" in body  # SPI = 150/200, formatted to 4 dp in the template


# ── /analyze with MS Project XML fixture ─────────────────────────────────────


def test_analyze_xml_fixture_returns_dashboard(client: object) -> None:
    """POST /analyze with the MSPDI fixture XML returns 200 with the dashboard."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    xml_bytes = _FIXTURE_XML.read_bytes()
    resp = c.post(
        "/analyze",
        data={"xml_file": (io.BytesIO(xml_bytes), "simple_network.xml", "text/xml")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.data.decode()
    assert any(band in body for band in ("GREEN", "YELLOW", "RED"))
    # simple_network.xml has project finish 2400 (A 960 + B 1440 FS chain)
    assert "2400" in body


# ── /analyze with garbage input → 400 ────────────────────────────────────────


def test_analyze_garbage_returns_400(client: object) -> None:
    """POST /analyze with garbage JSON returns 400 (never a 500 stack trace)."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.post("/analyze", data={"json_text": "not valid json {"})
    assert resp.status_code == 400
    body = resp.data.decode()
    assert "error" in body.lower() or "Error" in body


def test_analyze_empty_input_returns_400(client: object) -> None:
    """POST /analyze with no file and no JSON text returns 400."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.post("/analyze", data={"json_text": ""})
    assert resp.status_code == 400


def test_analyze_valid_json_wrong_schema_returns_400(client: object) -> None:
    """POST /analyze with syntactically valid JSON but wrong schema returns 400."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.post("/analyze", data={"json_text": '{"not_a_schedule": true}'})
    assert resp.status_code == 400


# ── /wipe clears state ────────────────────────────────────────────────────────


def test_wipe_clears_state_and_redirects(client: object) -> None:
    """POST /wipe destroys all in-memory state and redirects to /."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    # Load some state first
    sched = _minimal_schedule()
    c.post("/analyze", data={"json_text": sched.model_dump_json()})
    assert _STATE["analysis"] is not None

    resp = c.post("/wipe")
    # Should redirect to /
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert _STATE["analysis"] is None
    assert _STATE["schedule"] is None


def test_wipe_then_report_redirects_or_404(client: object) -> None:
    """After /wipe, GET /report.xlsx has no analysis to serve (redirects to /)."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    # Load state, then wipe
    sched = _minimal_schedule()
    c.post("/analyze", data={"json_text": sched.model_dump_json()})
    c.post("/wipe")

    resp = c.get("/report.xlsx")
    # No analysis → redirect to / (or 404 with message)
    assert resp.status_code in (301, 302, 303, 307, 308, 404)


def test_wipe_then_index_shows_no_dashboard(client: object) -> None:
    """After /wipe, GET / renders the form but no dashboard content."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    sched = _minimal_schedule()
    c.post("/analyze", data={"json_text": sched.model_dump_json()})
    c.post("/wipe")

    resp = c.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    # Dashboard heading should NOT appear when no analysis is held
    assert "Analysis Dashboard" not in body


# ── Report download routes ────────────────────────────────────────────────────


def test_report_xlsx_after_analysis(client: object) -> None:
    """GET /report.xlsx after an analysis returns 200 with xlsx content and non-empty body."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    sched = _minimal_schedule()
    c.post("/analyze", data={"json_text": sched.model_dump_json()})

    resp = c.get("/report.xlsx")
    assert resp.status_code == 200
    # xlsx magic bytes: PK (zip archive)
    assert resp.data[:2] == b"PK"
    # Content-type must be xlsx
    assert "spreadsheetml" in (resp.content_type or "")


def test_report_docx_after_analysis(client: object) -> None:
    """GET /report.docx after an analysis returns 200 with docx content and non-empty body."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    sched = _minimal_schedule()
    c.post("/analyze", data={"json_text": sched.model_dump_json()})

    resp = c.get("/report.docx")
    assert resp.status_code == 200
    # docx is also a zip; magic bytes PK
    assert resp.data[:2] == b"PK"
    assert "wordprocessingml" in (resp.content_type or "")


def test_report_xlsx_no_analysis_redirects(client: object) -> None:
    """GET /report.xlsx with no analysis redirects (no analysis in state)."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.get("/report.xlsx")
    assert resp.status_code in (301, 302, 303, 307, 308)


def test_report_docx_no_analysis_redirects(client: object) -> None:
    """GET /report.docx with no analysis redirects (no analysis in state)."""
    from flask.testing import FlaskClient

    c: FlaskClient = client  # type: ignore[assignment]
    resp = c.get("/report.docx")
    assert resp.status_code in (301, 302, 303, 307, 308)
