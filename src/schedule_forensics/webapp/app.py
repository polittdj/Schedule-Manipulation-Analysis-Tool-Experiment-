"""Flask application factory for Schedule Forensics localhost UI.

LAW 1 (Data Sovereignty):
- HOST is a module constant; the server is ONLY bound to 127.0.0.1.
- No schedule data is written to disk; all state lives in _STATE (in-memory).
- No external CDN / network calls; all CSS is inline in the template.
- Reports are streamed from io.BytesIO objects.

Routes:
  GET  /           -- CUI banner + upload form; renders dashboard if state held.
  POST /analyze    -- Parse uploaded MS Project XML / Primavera XER file (routed by
                      extension) or pasted JSON; run analysis; store.
  POST /wipe       -- Destroy all in-memory state; redirect to /.
  GET  /report.xlsx -- Stream Excel report for current analysis (or redirect /).
  GET  /report.docx -- Stream Word report for current analysis (or redirect /).
  GET  /health     -- Liveness check; returns {"status": "ok"}.
"""

from __future__ import annotations

import argparse
import io
import os
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

import pydantic
from flask import Flask, Response, redirect, render_template_string, request, send_file, url_for
from flask.typing import ResponseReturnValue

from schedule_forensics.analysis import ScheduleAnalysis, analyze_schedule
from schedule_forensics.cei import CEIError, compute_cei
from schedule_forensics.exec_summary import generate_executive_summary, health_band
from schedule_forensics.importers.com_msproject import (
    ComImporterError,
    ComUnavailableError,
    parse_mpp_via_com,
)
from schedule_forensics.importers.mpp_mpxj import ImporterError as MpxjImporterError
from schedule_forensics.importers.mpp_mpxj import parse_mpp
from schedule_forensics.importers.msp_xml import ImporterError as MspImporterError
from schedule_forensics.importers.msp_xml import parse_msp_xml_string
from schedule_forensics.importers.xer import ImporterError as XerImporterError
from schedule_forensics.importers.xer import parse_xer_string
from schedule_forensics.report_excel import CUI_NOTICE, build_excel_workbook
from schedule_forensics.report_word import build_word_document
from schedule_forensics.schemas import Schedule
from schedule_forensics.version_matcher import VersionMatchError

# ── LAW 1 constant ────────────────────────────────────────────────────────────
# HOST is fixed and intentionally NOT configurable: the server binds loopback only.
HOST: str = "127.0.0.1"

# ── Port configuration (host is fixed; only the port may vary) ────────────────
DEFAULT_PORT: int = 5000
PORT_ENV_VAR: str = "SF_PORT"

# ── Native .mpp/.mpx reader choice (user-selectable in the upload form) ───────
# "mpxj" -> cross-platform MPXJ subprocess (default); "com" -> MS Project COM
# automation (Windows-only). Only these two are valid; anything else falls back
# to MPXJ (fail safe, never crash on a tampered form value).
MPP_READER_MPXJ: str = "mpxj"
MPP_READER_COM: str = "com"
_VALID_MPP_READERS: frozenset[str] = frozenset({MPP_READER_MPXJ, MPP_READER_COM})

# ── In-memory state ───────────────────────────────────────────────────────────
# No schedule data is persisted to disk for the TEXT formats (XML/XER/JSON) -- they
# stay in _STATE only. Native binary .mpp/.mpx uploads are the one exception: MPXJ
# needs a real file path, so the bytes are written to a private, auto-deleted temp
# dir for the duration of the parse (see _parse_upload). That is LOCAL and ephemeral
# -- LAW 1 (no schedule data leaves the machine) is preserved.
#   "schedule"/"analysis" -> the latest version (drives the single-schedule dashboard
#   + report downloads); "versions" -> per-file summaries; "cei"/"cei_note" -> the
#   multi-version comparative result.
_STATE: dict[str, Any] = {
    "schedule": None,
    "analysis": None,
    "versions": [],
    "cei": (),
    "cei_note": None,
}


def _clear_state() -> None:
    """Destroy all uploaded / parsed / derived state (used by /wipe)."""
    _STATE["schedule"] = None
    _STATE["analysis"] = None
    _STATE["versions"] = []
    _STATE["cei"] = ()
    _STATE["cei_note"] = None


# ── Inline HTML template (no external assets — LAW 1) ─────────────────────────
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Schedule Forensics — Local Analysis Tool</title>
<style>
  /* All styles inline — no external CDN (LAW 1 compliance). */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 14px;
         background: #f4f6f8; color: #222; }

  /* CUI banner — always visible, above all content */
  .cui-banner {
    background: #ffd700; border-bottom: 3px solid #b8860b;
    padding: 10px 20px; font-weight: bold; color: #5a3e00;
    font-size: 13px; text-align: center;
  }

  /* Page wrapper */
  .page { max-width: 1100px; margin: 0 auto; padding: 20px; }
  h1 { font-size: 22px; margin-bottom: 6px; color: #1a2a3a; }
  h2 { font-size: 17px; margin: 20px 0 8px; color: #1a2a3a;
       border-bottom: 1px solid #c8d0da; padding-bottom: 4px; }
  h3 { font-size: 15px; margin: 14px 0 6px; color: #2c4a6a; }

  /* Forms */
  .card { background: #fff; border: 1px solid #d0d8e0; border-radius: 6px;
          padding: 20px; margin-bottom: 20px; }
  label { display: block; margin-bottom: 4px; font-weight: bold; color: #333; }
  textarea { width: 100%; font-family: monospace; font-size: 12px; padding: 8px;
             border: 1px solid #b0bcc8; border-radius: 4px; resize: vertical; }
  input[type="file"] { margin: 4px 0; }
  .btn { display: inline-block; padding: 8px 18px; border: none; border-radius: 4px;
         cursor: pointer; font-size: 14px; font-weight: bold; text-decoration: none; }
  .btn-primary { background: #1a6bbf; color: #fff; }
  .btn-primary:hover { background: #155090; }
  .btn-danger  { background: #c0392b; color: #fff; }
  .btn-danger:hover  { background: #922b21; }
  .btn-download { background: #2e7d32; color: #fff; }
  .btn-download:hover { background: #1b5e20; }
  .btn-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 14px; }

  /* Error box */
  .error-box { background: #fde8e8; border: 1px solid #e74c3c; border-radius: 4px;
               padding: 12px 16px; margin-bottom: 16px; color: #7b1c1c; }

  /* Health band */
  .band { display: inline-block; padding: 4px 14px; border-radius: 12px;
          font-weight: bold; font-size: 16px; letter-spacing: 1px; }
  .band-GREEN  { background: #c8f0c8; color: #145214; border: 1px solid #4caf50; }
  .band-YELLOW { background: #fff3cd; color: #7a5800; border: 1px solid #f0ad4e; }
  .band-RED    { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }

  /* Metric table */
  table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
  th { background: #2c4a6a; color: #fff; padding: 7px 10px; text-align: left; }
  td { padding: 6px 10px; border-bottom: 1px solid #e0e8f0; vertical-align: top; }
  tr:nth-child(even) td { background: #f7f9fb; }
  .status-PASS { background: #c8f0c8; color: #145214; font-weight: bold;
                 padding: 2px 8px; border-radius: 10px; }
  .status-FAIL { background: #f8d7da; color: #721c24; font-weight: bold;
                 padding: 2px 8px; border-radius: 10px; }
  .status-SKIPPED { background: #fff3cd; color: #7a5800; font-weight: bold;
                    padding: 2px 8px; border-radius: 10px; }
  .ext-tag { background: #e2d9f3; color: #4a235a; font-size: 11px;
             padding: 1px 6px; border-radius: 8px; }

  /* Summary grid */
  .summary-grid { display: grid; grid-template-columns: 200px 1fr; gap: 4px 12px; }
  .sg-label { font-weight: bold; color: #555; }
  .sg-value { color: #111; word-break: break-word; }

  /* Exec summary */
  .exec-pre { background: #f0f4f8; border: 1px solid #c8d4e0; border-radius: 4px;
              padding: 14px; font-family: monospace; font-size: 12px;
              white-space: pre-wrap; word-wrap: break-word; }

  /* Divider */
  .divider { border: none; border-top: 2px solid #c8d0da; margin: 24px 0; }
</style>
</head>
<body>

<!-- CUI banner: visible on every page before any input (LAW 1 / brief requirement) -->
<div class="cui-banner" id="cui-notice">{{ cui_notice }}</div>

<div class="page">
  <h1>Schedule Forensics &mdash; Local Analysis Tool</h1>
  <p style="color:#555;margin-bottom:16px;">
    All processing is performed locally on this machine. No data is transmitted externally.
  </p>

  {% if error %}
  <div class="error-box" role="alert">
    <strong>Error:</strong> {{ error }}
  </div>
  {% endif %}

  <!-- Upload / Input form -->
  <div class="card">
    <h2>Upload Schedule(s)</h2>
    <form method="post" action="/analyze" enctype="multipart/form-data">
      <div style="margin-bottom:14px;">
        <label for="schedule_files">Schedule file(s) &mdash; native MS Project
          <strong>.mpp</strong>, .mpx, Primavera .xer, or MS Project XML
          (select multiple status-dated versions for a comparative CEI view):</label>
        <input type="file" id="schedule_files" name="schedule_files"
               accept=".mpp,.mpx,.xer,.xml" multiple>
      </div>
      <fieldset
        style="margin-bottom:14px;border:1px solid #d0d8e0;border-radius:4px;padding:10px 14px;">
        <legend style="font-weight:bold;color:#333;padding:0 6px;">
          Native .mpp / .mpx reader</legend>
        <label style="font-weight:normal;display:block;margin-bottom:4px;">
          <input type="radio" name="mpp_reader" value="{{ mpxj_reader }}"
                 {{ "checked" if mpp_reader != com_reader else "" }}>
          <strong>MPXJ</strong> (Java helper, cross-platform &mdash; default; see docs/MPXJ.md)
        </label>
        <label style="font-weight:normal;display:block;">
          <input type="radio" name="mpp_reader" value="{{ com_reader }}"
                 {{ "checked" if mpp_reader == com_reader else "" }}>
          <strong>MS Project</strong> (COM automation &mdash; Windows + installed MS Project only)
        </label>
        <p style="font-size:11px;color:#777;margin-top:6px;">
          This choice applies only to native .mpp / .mpx files; .xer and MS Project XML
          ignore it. MPXJ runs a local Java converter; MS Project (COM) drives your
          installed MS Project. Both are fully local &mdash; nothing leaves this machine (LAW 1).
        </p>
      </fieldset>
      <div style="margin-bottom:14px;">
        <label for="json_text">Or paste Schedule JSON:</label>
        <textarea id="json_text" name="json_text" rows="6"
                  placeholder='{"name":"My Project","project_start":"2025-01-06T08:00:00",
"tasks":[...]}'
        >{{ json_prefill or "" }}</textarea>
      </div>
      <div class="btn-row">
        <button type="submit" class="btn btn-primary">Analyze</button>
      </div>
    </form>
  </div>

  {% if versions and versions|length > 1 %}
  <hr class="divider">
  <h2>Comparative Analysis &mdash; {{ versions|length }} versions</h2>

  <div class="card">
    <h3>Uploaded Versions</h3>
    <table>
      <thead><tr><th>File</th><th>Status date</th><th>Health</th>
        <th>Finish (working min)</th></tr></thead>
      <tbody>
        {% for v in versions %}
        <tr>
          <td>{{ v.name }}</td>
          <td>{{ v.status_date }}</td>
          <td><span class="band band-{{ v.band }}">{{ v.band }}</span></td>
          <td>{{ v.finish if v.finish is not none else "n/a" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3>Current Execution Index (CEI) &mdash; per period</h3>
    {% if cei_note %}
      <div class="error-box">{{ cei_note }}</div>
    {% endif %}
    {% if cei_periods %}
    <table>
      <thead>
        <tr><th>Period start</th><th>Period end</th><th>Forecast&#8209;to&#8209;finish</th>
            <th>Finished</th><th>CEI</th><th>Status</th></tr>
      </thead>
      <tbody>
        {% for p in cei_periods %}
        <tr>
          <td>{{ p.period_start.date() }}</td>
          <td>{{ p.period_end.date() }}</td>
          <td>{{ p.denominator }}</td>
          <td>{{ p.numerator }}</td>
          <td>{{ "%.2f"|format(p.cei) if p.cei is not none else "N/A" }}</td>
          <td><span class="status-{{ p.status }}">{{ p.status }}</span></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p style="font-size:11px;color:#777;margin-top:6px;">
      CEI (PASEG 10.4.5): tasks finished &divide; tasks forecast to finish, per period;
      &ge;0.95 gate (source-pending/VERIFY). The period-start snapshot is reconstructed
      from the prior version (tool-original capture method).
    </p>
    {% endif %}
  </div>
  {% endif %}{# end comparative #}

  {% if analysis %}
  <hr class="divider">
  {% if versions and versions|length > 1 %}
  <h2>Latest Version &mdash; Analysis Dashboard</h2>
  {% else %}
  <h2>Analysis Dashboard</h2>
  {% endif %}

  <!-- Health overview -->
  <div class="card">
    <h3>Overall Schedule Health</h3>
    <p>
      <span class="band band-{{ band }}">{{ band }}</span>
      &nbsp;
      {% if analysis.health_score is not none %}
        DCMA-14 integrity: <strong>{{ "%.1f"|format(analysis.health_score) }}%</strong>
        of runnable checks pass.
      {% else %}
        DCMA-14 integrity: <strong>not available</strong> (no runnable checks).
      {% endif %}
    </p>

    <div class="summary-grid" style="margin-top:12px;">
      <span class="sg-label">Project Finish (working minutes):</span>
      <span class="sg-value">
        {% if analysis.project_finish is not none %}
          {{ analysis.project_finish }}
        {% else %}
          n/a
        {% endif %}
      </span>

      <span class="sg-label">Project Finish (working days):</span>
      <span class="sg-value">
        {% if analysis.project_finish is not none %}
          {{ "%.2f"|format(analysis.project_finish / 480.0) }}
        {% else %}
          n/a
        {% endif %}
      </span>

      <span class="sg-label">Critical Path (UniqueIDs):</span>
      <span class="sg-value">
        {% if analysis.critical_path %}
          {{ analysis.critical_path | join(", ") }}
        {% else %}
          (none)
        {% endif %}
      </span>

      <span class="sg-label">Driving Path (UniqueIDs):</span>
      <span class="sg-value">
        {% if analysis.driving_chain %}
          {{ analysis.driving_chain | join(", ") }}
        {% else %}
          (none)
        {% endif %}
      </span>

      {% if analysis.cpm_error %}
      <span class="sg-label">CPM Error:</span>
      <span class="sg-value" style="color:#c0392b;">{{ analysis.cpm_error }}</span>
      {% endif %}
    </div>
  </div>

  <!-- Executive summary -->
  <div class="card">
    <h3>Executive Summary</h3>
    <pre class="exec-pre">{{ exec_summary }}</pre>
  </div>

  <!-- DCMA-14 table -->
  <div class="card">
    <h3>DCMA-14 Assessment</h3>
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Name</th>
          <th>Status</th>
          <th>Measured</th>
          <th>Threshold</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        {% for m in analysis.dcma %}
        <tr>
          <td>{{ m.metric_id }}</td>
          <td>
            {{ m.name }}
            {% if m.is_extension %}
              <span class="ext-tag"
                title="Tool-original extension; not reference-tool parity"
              >ext</span>
            {% endif %}
          </td>
          <td><span class="status-{{ m.status }}">{{ m.status }}</span></td>
          <td>{{ m.measured if m.measured is not none else "" }}</td>
          <td>{{ m.threshold if m.threshold is not none else "" }}</td>
          <td style="font-size:11px;color:#555;">{{ m.source }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p style="font-size:11px;color:#777;margin-top:6px;">
      <span class="ext-tag">ext</span> = tool-original extension; not reference-tool parity
      (DCMA-14 standard only; Acumen/SSI parity is claimed only for non-ext rows).
    </p>
  </div>

  <!-- Earned-value indices -->
  <div class="card">
    <h3>Earned-Value Indices (SPI / SPI(t))</h3>
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Name</th>
          <th>Status</th>
          <th>Measured</th>
          <th>Threshold</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        {% for m in analysis.performance_indices %}
        <tr>
          <td>{{ m.metric_id }}</td>
          <td>{{ m.name }}</td>
          <td><span class="status-{{ m.status }}">{{ m.status }}</span></td>
          <td>{{ "%.4f"|format(m.measured) if m.measured is not none else "" }}</td>
          <td>{{ m.threshold if m.threshold is not none else "" }}</td>
          <td style="font-size:11px;color:#555;">{{ m.source }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p style="font-size:11px;color:#777;margin-top:6px;">
      Earned-value indices need schedule data with budgeted cost + baseline dates;
      otherwise they are <strong>SKIPPED</strong> (never fabricated). The 0.95
      threshold is a common EVM management level, not a DCMA-14 number.
    </p>
  </div>

  <!-- Download reports + wipe -->
  <div class="card">
    <h3>Reports &amp; Session Control</h3>
    <div class="btn-row">
      <a href="/report.xlsx" class="btn btn-download">Download Excel (.xlsx)</a>
      <a href="/report.docx" class="btn btn-download">Download Word (.docx)</a>
    </div>
    <div class="btn-row" style="margin-top:16px;">
      <form method="post" action="/wipe"
            onsubmit="return confirm('Wipe all uploaded and analyzed data from memory?');">
        <button type="submit" class="btn btn-danger">Wipe Session Data</button>
      </form>
    </div>
    <p style="font-size:12px;color:#777;margin-top:8px;">
      Wipe destroys all in-memory uploaded, parsed, and derived data.
      No data is stored on disk by this tool.
    </p>
  </div>

  {% endif %}{# end if analysis #}
</div><!-- /page -->
</body>
</html>"""


def _parse_upload(upload: Any, *, mpp_reader: str = MPP_READER_MPXJ) -> Schedule:
    """Parse one uploaded file into a :class:`Schedule`, routed by extension.

    ``.mpp`` / ``.mpx`` (binary) need a real file path, so the bytes are written to a
    private, auto-deleted temp dir (LAW 1: local + ephemeral; nothing leaves the
    machine) and read by the chosen native reader: ``mpp_reader="mpxj"`` (the
    cross-platform MPXJ subprocess, default) or ``"com"`` (MS Project COM automation,
    Windows-only). ``.xer`` -> Primavera importer; anything else -> MS Project XML
    (MSPDI). The ``mpp_reader`` choice is ignored for the text formats. Raises the
    relevant importer error on failure.
    """
    name = (upload.filename or "").lower()
    if name.endswith((".mpp", ".mpx")):
        data = upload.read()
        suffix = os.path.splitext(name)[1] or ".mpp"
        with tempfile.TemporaryDirectory(prefix="sf_upload_") as tmp:
            tmp_path = os.path.join(tmp, f"schedule{suffix}")
            with open(tmp_path, "wb") as fh:
                fh.write(data)
            if mpp_reader == MPP_READER_COM:
                return parse_mpp_via_com(tmp_path)
            return parse_mpp(tmp_path)
    text = upload.read().decode("utf-8", errors="replace")
    if name.endswith(".xer"):
        return parse_xer_string(text)
    return parse_msp_xml_string(text)


def _latest_index(schedules: list[Schedule]) -> int:
    """Index of the version with the latest ``status_date`` (fallback: last given)."""
    best_idx = len(schedules) - 1
    best_date = None
    for idx, sched in enumerate(schedules):
        if sched.status_date is not None and (best_date is None or sched.status_date > best_date):
            best_date, best_idx = sched.status_date, idx
    return best_idx


def _compute_comparative(schedules: list[Schedule]) -> tuple[tuple[Any, ...], str | None]:
    """CEI across >=2 versions; ``(periods, note)``. <2 versions -> no comparison."""
    if len(schedules) < 2:
        return (), None
    try:
        return compute_cei(schedules), None
    except (CEIError, VersionMatchError) as exc:
        return (), f"CEI not computed: {exc}"


def _store_results(parsed: list[tuple[str, Schedule]]) -> None:
    """Populate _STATE from the parsed (filename, Schedule) pairs."""
    schedules = [sched for _, sched in parsed]
    analyses = [analyze_schedule(sched) for sched in schedules]
    latest = _latest_index(schedules)
    _STATE["schedule"] = schedules[latest]
    _STATE["analysis"] = analyses[latest]
    _STATE["versions"] = [
        {
            "name": name,
            "status_date": (sched.status_date.date().isoformat() if sched.status_date else "n/a"),
            "band": health_band(analysis).value,
            "finish": analysis.project_finish,
        }
        for (name, sched), analysis in zip(parsed, analyses, strict=True)
    ]
    cei_periods, cei_note = _compute_comparative(schedules)
    _STATE["cei"] = cei_periods
    _STATE["cei_note"] = cei_note


def _render_page(
    *,
    error: str | None = None,
    json_prefill: str | None = None,
    mpp_reader: str = MPP_READER_MPXJ,
    status: int = 200,
) -> ResponseReturnValue:
    """Render the page from current _STATE (single dashboard + comparative section)."""
    analysis: ScheduleAnalysis | None = _STATE.get("analysis")
    band = health_band(analysis).value if analysis is not None else None
    summary = generate_executive_summary(analysis) if analysis is not None else None
    html = render_template_string(
        _TEMPLATE,
        cui_notice=CUI_NOTICE,
        error=error,
        analysis=analysis,
        band=band,
        exec_summary=summary,
        json_prefill=json_prefill,
        mpp_reader=mpp_reader,
        mpxj_reader=MPP_READER_MPXJ,
        com_reader=MPP_READER_COM,
        versions=_STATE.get("versions") or [],
        cei_periods=_STATE.get("cei") or (),
        cei_note=_STATE.get("cei_note"),
    )
    return (html, status) if status != 200 else html


def create_app() -> Flask:
    """Flask application factory.

    Returns a configured Flask app. The in-memory state (_STATE) is
    module-level so it persists across requests within the same process,
    and is destroyed by POST /wipe.
    """
    app = Flask(__name__)

    @app.get("/")
    def index() -> ResponseReturnValue:
        """Render the upload form and (if present) the analysis dashboard."""
        return _render_page()

    @app.post("/analyze")
    def analyze() -> ResponseReturnValue:
        """Parse the uploaded schedule file(s) or pasted JSON; analyze; store in _STATE.

        Accepts one or MORE files (``.mpp``/``.mpx`` via MPXJ, ``.xer``, MS Project
        XML), routed by extension. Two or more status-dated versions also yield the
        multi-version comparative view (CEI).
        """
        uploads = [
            f
            for f in [*request.files.getlist("schedule_files"), *request.files.getlist("xml_file")]
            if f and f.filename
        ]
        json_text = (request.form.get("json_text") or "").strip()
        # Native .mpp/.mpx reader choice; unknown values fall back to MPXJ (fail safe).
        mpp_reader = (request.form.get("mpp_reader") or MPP_READER_MPXJ).strip().lower()
        if mpp_reader not in _VALID_MPP_READERS:
            mpp_reader = MPP_READER_MPXJ

        parsed: list[tuple[str, Schedule]] = []
        error: str | None = None

        if uploads:
            for upload in uploads:
                name = upload.filename or "uploaded file"
                try:
                    parsed.append((name, _parse_upload(upload, mpp_reader=mpp_reader)))
                except ComUnavailableError as exc:
                    # COM chosen but unavailable (e.g. not on Windows / no MS Project):
                    # surface its actionable message and point back at MPXJ / XML.
                    error = f"{name}: {exc}"
                    break
                except (
                    MspImporterError,
                    XerImporterError,
                    MpxjImporterError,
                    ComImporterError,
                ) as exc:
                    error = f"{name}: {exc}"
                    break
                except Exception as exc:  # noqa: BLE001
                    error = f"{name}: unexpected error reading the file: {exc}"
                    break
        elif json_text:
            try:
                parsed.append(("pasted JSON", Schedule.model_validate_json(json_text)))
            except pydantic.ValidationError as exc:
                # Surface pydantic errors concisely (no stack trace to the user).
                raw_errors = exc.errors()
                if raw_errors:
                    first = raw_errors[0]
                    loc = " -> ".join(str(x) for x in first["loc"])
                    error = f"JSON validation error at '{loc}': {first['msg']!s}"
                else:
                    error = f"JSON validation error: {exc}"
            except Exception as exc:  # noqa: BLE001
                error = f"Unexpected error reading JSON: {exc}"
        else:
            error = "No input provided. Upload .mpp / .xer / MS Project XML file(s), or paste JSON."

        if error is not None:
            return _render_page(
                error=error, json_prefill=json_text or None, mpp_reader=mpp_reader, status=400
            )

        _store_results(parsed)
        return _render_page(mpp_reader=mpp_reader)

    @app.post("/wipe")
    def wipe() -> ResponseReturnValue:
        """Destroy all in-memory uploaded / parsed / derived state."""
        _clear_state()
        return redirect(url_for("index"))

    @app.get("/report.xlsx")
    def report_xlsx() -> ResponseReturnValue:
        """Stream the Excel report for the current in-memory analysis."""
        analysis: ScheduleAnalysis | None = _STATE.get("analysis")
        if analysis is None:
            return redirect(url_for("index"))
        buf = io.BytesIO()
        build_excel_workbook(analysis).save(buf)
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name="schedule_forensics_report.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.get("/report.docx")
    def report_docx() -> ResponseReturnValue:
        """Stream the Word report for the current in-memory analysis."""
        analysis: ScheduleAnalysis | None = _STATE.get("analysis")
        if analysis is None:
            return redirect(url_for("index"))
        buf = io.BytesIO()
        build_word_document(analysis).save(buf)
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name="schedule_forensics_report.docx",
            mimetype=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )

    @app.get("/health")
    def health() -> Response:
        """Liveness endpoint — no schedule data is returned."""
        return app.response_class(
            response='{"status": "ok"}',
            status=200,
            mimetype="application/json",
        )

    return app


def _validate_port(port: int, *, source: str) -> int:
    """Reject ports outside the valid TCP range (fail closed, never silently clamp)."""
    if not (1 <= port <= 65535):
        raise ValueError(f"{source} must be in the range 1..65535, got {port}.")
    return port


def resolve_port(cli_port: int | None, environ: Mapping[str, str]) -> int:
    """Resolve the UI port: ``--port`` CLI arg > ``SF_PORT`` env var > default 5000.

    Only the port is configurable; HOST stays fixed at 127.0.0.1 (LAW 1). An
    out-of-range or non-integer value raises ``ValueError`` rather than silently
    falling back, so the operator always binds the port they intended.
    """
    if cli_port is not None:
        return _validate_port(cli_port, source="--port")
    raw = environ.get(PORT_ENV_VAR)
    if raw is not None and raw.strip() != "":
        try:
            env_port = int(raw.strip())
        except ValueError as exc:
            raise ValueError(f"{PORT_ENV_VAR}={raw!r} is not a valid integer port.") from exc
        return _validate_port(env_port, source=PORT_ENV_VAR)
    return DEFAULT_PORT


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for running the development server locally.

    The port is configurable via ``--port`` or the ``SF_PORT`` environment
    variable (default 5000); ``--port`` takes precedence. The host is fixed at
    127.0.0.1 (LAW 1) and is intentionally NOT configurable.
    """
    parser = argparse.ArgumentParser(
        prog="schedule_forensics.webapp",
        description="Run the Schedule Forensics localhost UI (binds 127.0.0.1 only).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Port to bind on 127.0.0.1 (default: {PORT_ENV_VAR} env var, else {DEFAULT_PORT}).",
    )
    args = parser.parse_args(argv)
    port = resolve_port(args.port, os.environ)
    app = create_app()
    app.run(host=HOST, port=port)


if __name__ == "__main__":
    main()
