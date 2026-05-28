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
from schedule_forensics.cpm import CPMError
from schedule_forensics.diff_engine import VersionPairDiff, diff_consecutive
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
from schedule_forensics.phases import Phase, compute_phases
from schedule_forensics.report_excel import CUI_NOTICE, build_excel_workbook
from schedule_forensics.report_word import build_word_document
from schedule_forensics.schemas import Schedule
from schedule_forensics.sra import SRAResult, run_sra
from schedule_forensics.trend_analysis import TrendReport, analyze_version_trends
from schedule_forensics.version_matcher import VersionMatchError

# ── LAW 1 constant ────────────────────────────────────────────────────────────
# HOST is fixed and intentionally NOT configurable: the server binds loopback only.
HOST: str = "127.0.0.1"

# ── Port configuration (host is fixed; only the port may vary) ────────────────
DEFAULT_PORT: int = 5000
PORT_ENV_VAR: str = "SF_PORT"

# ── Schedule Risk Analysis (Monte Carlo) defaults ─────────────────────────────
# SRA cost is iterations x CPM, run synchronously for the displayed version only.
# A fixed seed keeps the result reproducible (LAW 2 / determinism); the iteration
# count is a deliberate UI default that balances tail stability against request
# latency. The result is computed ONCE here and reused by the dashboard and both
# report downloads, so the UI and the reports always agree.
_SRA_ITERATIONS: int = 1000
_SRA_SEED: int = 12345
# Auto-SRA is skipped above this non-summary activity count to keep /analyze
# responsive (the cost grows with activities x iterations). The schedule is still
# fully analyzed; the skip is surfaced to the user, never silent.
_SRA_MAX_TASKS: int = 300
# How many highest-criticality activities to surface in the dashboard card.
_SRA_TOP_CRITICALITY: int = 15
_MINUTES_PER_DAY: float = 480.0

# How many most-moved task deltas to surface per version pair in the diff card.
_DIFF_TOP_CHANGES: int = 12

# ── Upload cap ────────────────────────────────────────────────────────────────
# Multi-file uploads are capped at this count per /analyze request. The engine
# handles N arbitrary; this guards the UI from accidental mass uploads.
MAX_UPLOADS: int = 20

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
    "trends": None,
    "sra": None,
    "sra_note": None,
    "diffs": (),
    "phases": (),
    "phases_note": None,
}


def _clear_state() -> None:
    """Destroy all uploaded / parsed / derived state (used by /wipe)."""
    _STATE["schedule"] = None
    _STATE["analysis"] = None
    _STATE["versions"] = []
    _STATE["cei"] = ()
    _STATE["cei_note"] = None
    _STATE["trends"] = None
    _STATE["sra"] = None
    _STATE["sra_note"] = None
    _STATE["diffs"] = ()
    _STATE["phases"] = ()
    _STATE["phases_note"] = None


# ── Inline HTML template (no external assets — LAW 1) ─────────────────────────
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Schedule Forensics — Local Analysis Tool</title>
<style>
  /* All styles inline — no external CDN / web fonts (LAW 1 compliance). */
  /* ── Dark theme palette (CSS variables; inline styles reference these too) ── */
  :root {
    --bg: #0d1117; --bg-grad: #0a0e14;
    --surface: #161b22; --surface-2: #1b2230; --surface-3: #21283400;
    --border: #2b3441; --border-soft: #232b36;
    --text: #e6edf3; --text-dim: #aeb9c5; --text-muted: #7d8896;
    --accent: #4a9eff; --accent-hover: #6cb0ff; --accent-strong: #1f6feb;
    --ok-bg: #102a1a; --ok-text: #57d364; --ok-bd: #2ea043;
    --bad-bg: #2c1316; --bad-text: #ff7b72; --bad-bd: #da3633;
    --warn-bg: #2e2510; --warn-text: #e3b341; --warn-bd: #9e6a03;
    --ext-bg: #241a3a; --ext-text: #cdb4fb; --ext-bd: #5a3aa0;
    --shadow: 0 1px 3px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.22);
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial,
                 sans-serif; font-size: 14px; line-height: 1.5;
    color: var(--text);
    background: radial-gradient(1200px 600px at 50% -10%, #11202f 0%, var(--bg) 45%) no-repeat,
                var(--bg-grad);
    background-attachment: fixed; -webkit-font-smoothing: antialiased;
  }

  /* CUI banner — always visible, above all content (compliance marker) */
  .cui-banner {
    background: linear-gradient(180deg, #e3b341 0%, #c9971f 100%);
    border-bottom: 2px solid #7a5a06; color: #1a1205;
    padding: 9px 20px; font-weight: 700; font-size: 12.5px; text-align: center;
    letter-spacing: .2px; text-shadow: 0 1px 0 rgba(255,255,255,.25);
  }

  /* Page wrapper + app header */
  .page { max-width: 1120px; margin: 0 auto; padding: 26px 22px 56px; }
  .app-header { display: flex; align-items: center; gap: 14px; margin-bottom: 6px; }
  .app-mark { width: 38px; height: 38px; border-radius: 9px; flex: none;
    background: linear-gradient(150deg, #1f6feb, #4a9eff); position: relative;
    box-shadow: 0 2px 10px rgba(31,111,235,.45); }
  .app-mark::before { content: ""; position: absolute; inset: 10px 9px;
    border: 2.5px solid #eaf2fb; border-radius: 50%; width: 16px; height: 16px; }
  .app-mark::after { content: ""; position: absolute; right: 7px; bottom: 7px;
    width: 9px; height: 2.5px; background: #eaf2fb; transform: rotate(45deg); border-radius: 2px; }
  h1 { font-size: 21px; font-weight: 650; letter-spacing: -.2px; color: var(--text); }
  .app-subtitle { color: var(--text-muted); font-size: 12.5px; margin-bottom: 22px; }
  .pill-offline { display: inline-block; margin-left: 10px; padding: 2px 9px; font-size: 11px;
    font-weight: 600; color: var(--ok-text); background: var(--ok-bg);
    border: 1px solid var(--ok-bd); border-radius: 20px; vertical-align: middle;
    letter-spacing: .3px; }
  h2 { font-size: 16px; font-weight: 620; margin: 26px 0 12px; color: var(--text);
       padding-bottom: 7px; border-bottom: 1px solid var(--border); letter-spacing: -.1px; }
  h3 { font-size: 14.5px; font-weight: 620; margin: 2px 0 10px; color: var(--text); }
  h4 { font-size: 12.5px; font-weight: 650; margin: 18px 0 6px; color: var(--text-dim);
       text-transform: uppercase; letter-spacing: .6px; }

  /* Cards */
  .card { background: linear-gradient(180deg, var(--surface) 0%, #13181f 100%);
          border: 1px solid var(--border); border-radius: 12px;
          padding: 20px 22px; margin-bottom: 18px; box-shadow: var(--shadow); }

  /* Forms */
  label { display: block; margin-bottom: 5px; font-weight: 600; color: var(--text-dim); }
  textarea {
    width: 100%; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 12px; padding: 10px 12px; color: var(--text); background: #0c1118;
    border: 1px solid var(--border); border-radius: 8px; resize: vertical; }
  textarea:focus, input:focus-visible { outline: none; border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(74,158,255,.18); }
  textarea::placeholder { color: #56606c; }
  input[type="file"] { margin: 6px 0; color: var(--text-dim); font-size: 13px; }
  input[type="file"]::file-selector-button {
    margin-right: 12px; padding: 7px 13px; border: 1px solid var(--border); border-radius: 7px;
    background: var(--surface-2); color: var(--text); font-weight: 600; cursor: pointer; }
  input[type="file"]::file-selector-button:hover {
    border-color: var(--accent); color: var(--accent-hover); }
  fieldset { border: 1px solid var(--border) !important; border-radius: 9px; background: #0f141b; }
  legend { color: var(--text-dim) !important; }
  .btn { display: inline-block; padding: 9px 18px; border: 1px solid transparent;
         border-radius: 8px; cursor: pointer; font-size: 13.5px; font-weight: 650;
         text-decoration: none; transition: background .12s, border-color .12s, transform .04s; }
  .btn:active { transform: translateY(1px); }
  .btn-primary { background: var(--accent-strong); color: #fff; }
  .btn-primary:hover { background: #2b7df0; }
  .btn-danger  { background: transparent; color: var(--bad-text); border-color: var(--bad-bd); }
  .btn-danger:hover  { background: var(--bad-bg); }
  .btn-download { background: var(--surface-2); color: var(--text); border-color: var(--border); }
  .btn-download:hover { border-color: var(--accent); color: var(--accent-hover); }
  .btn-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 14px; }

  /* Error box */
  .error-box { background: var(--bad-bg); border: 1px solid var(--bad-bd); border-radius: 9px;
               padding: 12px 16px; margin-bottom: 16px; color: var(--bad-text); }

  /* Health band */
  .band { display: inline-block; padding: 4px 15px; border-radius: 20px;
          font-weight: 700; font-size: 14px; letter-spacing: 1px; }
  .band-GREEN  { background: var(--ok-bg); color: var(--ok-text); border: 1px solid var(--ok-bd); }
  .band-YELLOW { background: var(--warn-bg); color: var(--warn-text);
                 border: 1px solid var(--warn-bd); }
  .band-RED    { background: var(--bad-bg); color: var(--bad-text);
                 border: 1px solid var(--bad-bd); }

  /* Tables */
  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px;
          border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  th { background: var(--surface-2); color: var(--text-dim); padding: 9px 12px; text-align: left;
       font-weight: 650; font-size: 11.5px; text-transform: uppercase; letter-spacing: .5px;
       border-bottom: 1px solid var(--border); }
  td { padding: 8px 12px; border-bottom: 1px solid var(--border-soft); vertical-align: top;
       color: var(--text-dim); }
  tr:last-child td { border-bottom: none; }
  tbody tr:nth-child(even) td { background: rgba(255,255,255,.018); }
  tbody tr:hover td { background: rgba(74,158,255,.07); }
  .status-PASS, .status-FAIL, .status-SKIPPED { font-weight: 650; font-size: 11.5px;
    padding: 2px 9px; border-radius: 20px; display: inline-block; border: 1px solid; }
  .status-PASS { background: var(--ok-bg);  color: var(--ok-text);  border-color: var(--ok-bd); }
  .status-FAIL { background: var(--bad-bg); color: var(--bad-text); border-color: var(--bad-bd); }
  .status-SKIPPED { background: var(--warn-bg); color: var(--warn-text);
                    border-color: var(--warn-bd); }
  .ext-tag { background: var(--ext-bg); color: var(--ext-text); border: 1px solid var(--ext-bd);
             font-size: 10.5px; font-weight: 600; padding: 1px 7px; border-radius: 8px; }

  /* Summary grid */
  .summary-grid { display: grid; grid-template-columns: 220px 1fr; gap: 7px 14px; }
  .sg-label { font-weight: 600; color: var(--text-muted); }
  .sg-value { color: var(--text); word-break: break-word; }

  /* Exec summary */
  .exec-pre { background: #0c1118; border: 1px solid var(--border); border-radius: 9px;
              padding: 16px; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
              font-size: 12px; line-height: 1.6; color: var(--text-dim);
              white-space: pre-wrap; word-wrap: break-word; }

  /* Divider */
  .divider { border: none; border-top: 1px solid var(--border); margin: 30px 0; }
  a { color: var(--accent); }
</style>
</head>
<body>

<!-- CUI banner: visible on every page before any input (LAW 1 / brief requirement) -->
<div class="cui-banner" id="cui-notice">{{ cui_notice }}</div>

<div class="page">
  <div class="app-header">
    <div class="app-mark" aria-hidden="true"></div>
    <h1>Schedule Forensics<span class="pill-offline">&#9679; LOCAL &middot; 127.0.0.1</span></h1>
  </div>
  <p class="app-subtitle">
    Forensic schedule analysis &mdash; DCMA-14, critical &amp; driving path, Monte-Carlo risk,
    and multi-version comparison. All processing stays on this machine; nothing is transmitted
    externally.
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
          (select up to 20 status-dated versions; the dashboard orders them by status
          date and shows the resulting time phases plus the comparative CEI view):</label>
        <input type="file" id="schedule_files" name="schedule_files"
               accept=".mpp,.mpx,.xer,.xml" multiple>
      </div>
      <fieldset
        style="margin-bottom:14px;padding:10px 14px;">
        <legend style="font-weight:bold;color:var(--text-dim);padding:0 6px;">
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
        <p style="font-size:11px;color:var(--text-muted);margin-top:6px;">
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

  {% if phases or phases_note %}
  <div class="card">
    <h3>Schedule Phases{% if phases %} &mdash; {{ phases|length }} phase(s){% endif %}</h3>
    {% if phases_note %}
      <div class="error-box">{{ phases_note }}</div>
    {% endif %}
    {% if phases %}
    <p style="color:var(--text-dim);margin-bottom:8px;">
      Phase 1 starts at the earliest date in the first schedule; each subsequent
      phase runs from the prior status date to the current status date.
    </p>
    <table>
      <thead>
        <tr><th>#</th><th>Schedule</th><th>Phase start</th>
            <th>Phase end (status date)</th><th>Calendar days</th></tr>
      </thead>
      <tbody>
        {% for p in phases %}
        <tr>
          <td>{{ p.index }}</td>
          <td>{{ p.schedule_name }}</td>
          <td>{{ p.phase_start.date() }}</td>
          <td>{{ p.phase_end.date() }}</td>
          <td>{{ "%.1f"|format(p.duration_days) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </div>
  {% endif %}

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
    <p style="font-size:11px;color:var(--text-muted);margin-top:6px;">
      CEI (PASEG 10.4.5): tasks finished &divide; tasks forecast to finish, per period;
      &ge;0.95 gate (source-pending/VERIFY). The period-start snapshot is reconstructed
      from the prior version (tool-original capture method).
    </p>
    {% endif %}
  </div>

  {% if trends and trends.n_versions > 1 %}
  <div class="card">
    <h3>Trend Analysis
      <span class="ext-tag" title="Tool-original extension; not reference-tool parity">ext</span>
    </h3>
    {% if trends.finish_days_net_change is not none %}
    <p>
      Project finish moved from
      <strong>{{ "%.1f"|format(trends.finish_days_first) }}</strong> to
      <strong>{{ "%.1f"|format(trends.finish_days_last) }}</strong> working days across
      {{ trends.n_versions }} versions
      (<strong>{{ "%+.1f"|format(trends.finish_days_net_change) }}</strong> days &mdash;
      {% if trends.finish_days_net_change > 0 %}slipping
      {% elif trends.finish_days_net_change < 0 %}pulling in
      {% else %}no net change{% endif %}).
    </p>
    {% endif %}

    <h4>Version trajectory</h4>
    <table>
      <thead><tr><th>#</th><th>Status date</th><th>Finish (working days)</th>
        <th>Health</th><th>Band</th><th>Critical tasks</th></tr></thead>
      <tbody>
        {% for s in trends.snapshots %}
        <tr>
          <td>{{ s.index + 1 }}</td>
          <td>{{ s.status_date.date() if s.status_date else "n/a" }}</td>
          <td>{{ "%.1f"|format(s.project_finish_days)
                if s.project_finish_days is not none else "n/a" }}</td>
          <td>{{ "%.1f"|format(s.health_score) ~ "%"
                if s.health_score is not none else "n/a" }}</td>
          <td><span class="band band-{{ s.band }}">{{ s.band }}</span></td>
          <td>{{ s.n_critical }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <h4>Float erosion (per task, across versions)</h4>
    <p>
      {% for band, n in trends.band_counts.items() %}{{ band }}:
        <strong>{{ n }}</strong>{{ ", " if not loop.last else "" }}{% endfor %}
    </p>
    {% set eroders = trends.worst_eroders(8) %}
    {% if eroders %}
    <table>
      <thead><tr><th>UniqueID</th><th>Earliest float (d)</th><th>Latest float (d)</th>
        <th>Net change (d)</th><th>Trend</th></tr></thead>
      <tbody>
        {% for t in eroders %}
        <tr>
          <td>{{ t.unique_id }}</td>
          <td>{{ "%.1f"|format(t.earliest_float_days) }}</td>
          <td>{{ "%.1f"|format(t.latest_float_days) }}</td>
          <td>{{ "%+.1f"|format(t.net_change_days) }}</td>
          <td>
            <span class="status-{{ 'FAIL'
                  if t.trend in ('CRITICAL', 'SEVERE_EROSION')
                  else 'SKIPPED' }}">{{ t.trend }}</span>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
    <p style="font-size:11px;color:var(--text-muted);margin-top:6px;">
      <span class="ext-tag">ext</span> Trend Analysis is a tool-original extension
      (the cross-version trajectory framing and float-erosion bands); the per-version
      finish and health values are objective, but the trend layer is not reference-tool parity.
    </p>
  </div>
  {% endif %}{# end trend analysis #}

  {% if diffs %}
  <div class="card">
    <h3>Version-to-Version Changes</h3>
    <p style="color:var(--text-dim);margin-bottom:8px;">
      Objective deltas between consecutive status updates (tasks matched by UniqueID).
      Date and float shifts are in working days; a positive finish shift means the task moved later.
    </p>
    {% for d in diffs %}
    <h4>{{ d.previous_status }} &rarr; {{ d.current_status }}</h4>
    <div class="summary-grid" style="margin-bottom:8px;">
      <span class="sg-label">Tasks added / deleted:</span>
      <span class="sg-value">{{ d.n_added }} / {{ d.n_deleted }}</span>
      <span class="sg-label">Became critical / recovered:</span>
      <span class="sg-value">{{ d.n_became_critical }} / {{ d.n_recovered }}</span>
      <span class="sg-label">Logic links added + removed:</span>
      <span class="sg-value">{{ d.n_logic_changes }}</span>
    </div>
    {% if d.top_changes %}
    <table>
      <thead><tr><th>UniqueID</th><th>Finish shift (d)</th><th>Float &Delta; (d)</th>
        <th>Flag</th><th>Preds +</th><th>Preds &minus;</th></tr></thead>
      <tbody>
        {% for t in d.top_changes %}
        <tr>
          <td>{{ t.unique_id }}</td>
          <td>{{ "%+.1f"|format(t.finish_shift_days) }}</td>
          <td>{{ "%+.1f"|format(t.float_delta_days) }}</td>
          <td>
            {% if t.became_critical %}<span class="status-FAIL">became critical</span>
            {% elif t.recovered %}<span class="status-PASS">recovered</span>
            {% else %}&mdash;{% endif %}
          </td>
          <td>{{ t.preds_added | join(", ") }}</td>
          <td>{{ t.preds_removed | join(", ") }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% if d.n_notable > d.top_changes|length %}
    <p style="font-size:11px;color:var(--text-muted);">
      Showing the {{ d.top_changes|length }} largest of
      {{ d.n_notable }} changed activities.</p>
    {% endif %}
    {% else %}
    <p style="color:var(--text-dim);">No task-level changes between these versions.</p>
    {% endif %}
    {% endfor %}
    <p style="font-size:11px;color:var(--text-muted);margin-top:6px;">
      Objective version deltas (the Acumen ProjectTimeNow / ProjectPreviousTimeNow comparative
      pattern) &mdash; measured facts, not a score; no threshold is applied.
    </p>
  </div>
  {% endif %}{# end version diff #}
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
      <span class="sg-value" style="color:var(--bad-text);">{{ analysis.cpm_error }}</span>
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
          <td style="font-size:11px;color:var(--text-dim);">{{ m.source }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p style="font-size:11px;color:var(--text-muted);margin-top:6px;">
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
          <td style="font-size:11px;color:var(--text-dim);">{{ m.source }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p style="font-size:11px;color:var(--text-muted);margin-top:6px;">
      Earned-value indices need schedule data with budgeted cost + baseline dates;
      otherwise they are <strong>SKIPPED</strong> (never fabricated). The 0.95
      threshold is a common EVM management level, not a DCMA-14 number.
    </p>
  </div>

  {% if sra %}
  <!-- Schedule Risk Analysis (Monte Carlo) -->
  <div class="card">
    <h3>Schedule Risk Analysis (Monte Carlo)</h3>
    <p style="color:var(--text-dim);margin-bottom:8px;">
      {{ sra.iterations }} iterations over per-activity duration uncertainty
      (re-running the CPM each trial). Finish values are in working days.
    </p>
    <div class="summary-grid" style="margin-bottom:12px;">
      <span class="sg-label">Deterministic finish (days):</span>
      <span class="sg-value">{{ "%.1f"|format(sra.deterministic_days) }}</span>
      <span class="sg-label">Mean finish (days):</span>
      <span class="sg-value">{{ "%.1f"|format(sra.mean_days) }}</span>
    </div>
    <table>
      <thead><tr><th>Percentile</th><th>Finish (working days)</th></tr></thead>
      <tbody>
        <tr><td>P50</td><td>{{ "%.1f"|format(sra.p50_days) }}</td></tr>
        <tr><td>P80</td><td>{{ "%.1f"|format(sra.p80_days) }}</td></tr>
        <tr><td>P95</td><td>{{ "%.1f"|format(sra.p95_days) }}</td></tr>
      </tbody>
    </table>
    {% if sra.top_criticality %}
    <h4>Criticality index (top activities)</h4>
    <table>
      <thead><tr><th>UniqueID</th><th>Criticality index (%)</th></tr></thead>
      <tbody>
        {% for uid, pct in sra.top_criticality %}
        <tr><td>{{ uid }}</td><td>{{ "%.1f"|format(pct) }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p style="color:var(--text-dim);">No activity reached the critical path in any iteration.</p>
    {% endif %}
    <p style="font-size:11px;color:var(--text-muted);margin-top:6px;">
      The SRA method (finish distribution + criticality index) mirrors Acumen Fuse
      / Primavera Risk Analysis (reference parity). The default duration spread that
      seeds it is the tool's own heuristic (source&#8209;pending) &mdash; in an engagement
      the analyst supplies per&#8209;activity risk ranges; the distribution models duration
      uncertainty only.
    </p>
  </div>
  {% elif sra_note %}
  <!-- SRA skipped (e.g. schedule too large for the in-browser Monte-Carlo run) -->
  <div class="card">
    <h3>Schedule Risk Analysis (Monte Carlo)</h3>
    <p style="color:var(--text-dim);">{{ sra_note }}</p>
  </div>
  {% endif %}{# end SRA #}

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
    <p style="font-size:12px;color:var(--text-muted);margin-top:8px;">
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


def _compute_trends(schedules: list[Schedule]) -> TrendReport | None:
    """Multi-version trend report across >=2 versions; ``None`` if not computable.

    Needs a ``status_date`` on every version to order the series; if one is missing
    (``VersionMatchError``) the trend section is simply omitted (fail safe, never
    a crash or a fabricated trajectory)."""
    if len(schedules) < 2:
        return None
    try:
        return analyze_version_trends(schedules)
    except VersionMatchError:
        return None


def _compute_diffs(schedules: list[Schedule]) -> tuple[VersionPairDiff, ...]:
    """Objective consecutive version-pair deltas across >=2 versions; ``()`` if not computable.

    Like the trend report, this needs a ``status_date`` on every version to order
    the series (``VersionMatchError``) and a schedulable network in each
    (``CPMError``); either way the diff section is simply omitted (fail safe, never
    a crash or a fabricated delta)."""
    if len(schedules) < 2:
        return ()
    try:
        return diff_consecutive(schedules)
    except (VersionMatchError, CPMError):
        return ()


def _compute_sra(schedule: Schedule) -> tuple[SRAResult | None, str | None]:
    """Monte-Carlo SRA for the displayed schedule; ``(result, note)``.

    Run only for the displayed (latest) version -- it is expensive (``iterations``
    x CPM) and the dashboard shows one schedule. Two fail-safe paths return no
    result (never a fabricated distribution):

    * **too large** -- above ``_SRA_MAX_TASKS`` non-summary activities the run is
      skipped to keep the request responsive; the ``note`` says so (the
      deterministic analysis is unaffected), so the skip is transparent, not silent.
    * **unschedulable base** -- ``run_sra`` raises ``CPMError`` on a logic cycle or
      a deferred ALAP/MSO/MFO constraint; the card is simply omitted (the dashboard
      already surfaces the CPM error separately), so ``note`` stays ``None``."""
    n_activities = sum(1 for t in schedule.tasks if not t.is_summary)
    if n_activities > _SRA_MAX_TASKS:
        return None, (
            f"Schedule Risk Analysis was skipped automatically: {n_activities} activities exceed "
            f"the {_SRA_MAX_TASKS}-activity threshold for the in-browser Monte-Carlo run. The "
            f"deterministic analysis above is complete; run SRA via the library "
            f"(schedule_forensics.sra.run_sra) for large schedules."
        )
    try:
        return run_sra(schedule, iterations=_SRA_ITERATIONS, seed=_SRA_SEED), None
    except CPMError:
        return None, None


def _compute_phases_view(
    parsed: list[tuple[str, Schedule]],
) -> tuple[tuple[Phase, ...], str | None]:
    """Return the time phases for the uploaded series, or ``((), note)`` on error.

    Pairs each schedule with its uploaded filename so the dashboard shows the
    file the operator actually selected (rather than the project's internal
    ``Schedule.name``, which is often a default like 'Project1'). Missing
    ``status_date`` on any version surfaces as a note (LAW 2 -- fail closed).
    """
    if not parsed:
        return (), None
    relabelled = [s.model_copy(update={"name": name}) for name, s in parsed]
    try:
        return compute_phases(relabelled), None
    except VersionMatchError as exc:
        return (), f"Phases unavailable: {exc}."


def _store_results(parsed: list[tuple[str, Schedule]]) -> None:
    """Populate _STATE from the parsed (filename, Schedule) pairs."""
    schedules = [sched for _, sched in parsed]
    analyses = [analyze_schedule(sched) for sched in schedules]
    latest = _latest_index(schedules)
    _STATE["schedule"] = schedules[latest]
    _STATE["analysis"] = analyses[latest]
    sra_result, sra_note = _compute_sra(schedules[latest])
    _STATE["sra"] = sra_result
    _STATE["sra_note"] = sra_note
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
    _STATE["trends"] = _compute_trends(schedules)
    _STATE["diffs"] = _compute_diffs(schedules)
    phases, phases_note = _compute_phases_view(parsed)
    _STATE["phases"] = phases
    _STATE["phases_note"] = phases_note


def _sra_view(sra: SRAResult | None) -> dict[str, Any] | None:
    """Pre-format an :class:`SRAResult` for the template (working-day display values).

    Keeps the Jinja template free of arithmetic and sorting: finish offsets are
    converted to working days (offset / 480.0) and the criticality index is ranked
    descending (then by ``unique_id`` for a stable tie-break), filtered to the
    activities that reached the critical path at least once, and capped. ``None``
    in -> ``None`` out (the card is simply omitted)."""
    if sra is None:
        return None
    ranked = sorted(sra.criticality_index.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [(uid, 100.0 * ci) for uid, ci in ranked if ci > 0.0][:_SRA_TOP_CRITICALITY]
    return {
        "iterations": sra.iterations,
        "deterministic_days": sra.deterministic_finish / _MINUTES_PER_DAY,
        "mean_days": sra.mean_finish / _MINUTES_PER_DAY,
        "p50_days": sra.p50 / _MINUTES_PER_DAY,
        "p80_days": sra.p80 / _MINUTES_PER_DAY,
        "p95_days": sra.p95 / _MINUTES_PER_DAY,
        "top_criticality": top,
    }


def _diffs_view(diffs: tuple[VersionPairDiff, ...]) -> list[dict[str, Any]]:
    """Pre-format consecutive version-pair diffs for the template.

    Keeps the Jinja template free of arithmetic/sorting: per pair, summarise the
    objective counts (added/deleted/became-critical/recovered/logic changes) and
    surface the most-moved task deltas first. A delta is "notable" when anything
    actually changed (finish/float shift, criticality flip, or a logic edit);
    notable deltas are ranked by absolute finish shift (then ``unique_id``) and
    capped. Shifts render in working days (offset / 480.0)."""
    views: list[dict[str, Any]] = []
    for pair in diffs:
        notable = [
            d
            for d in pair.task_deltas
            if d.became_critical
            or d.recovered
            or d.finish_shift_minutes
            or d.total_float_delta_minutes
            or d.predecessors_added
            or d.predecessors_removed
        ]
        notable.sort(key=lambda d: (-abs(d.finish_shift_minutes), d.unique_id))
        top = [
            {
                "unique_id": d.unique_id,
                "finish_shift_days": d.finish_shift_minutes / _MINUTES_PER_DAY,
                "float_delta_days": d.total_float_delta_minutes / _MINUTES_PER_DAY,
                "became_critical": d.became_critical,
                "recovered": d.recovered,
                "preds_added": list(d.predecessors_added),
                "preds_removed": list(d.predecessors_removed),
            }
            for d in notable[:_DIFF_TOP_CHANGES]
        ]
        views.append(
            {
                "previous_status": pair.previous_status.date().isoformat(),
                "current_status": pair.current_status.date().isoformat(),
                "n_added": len(pair.added_ids),
                "n_deleted": len(pair.deleted_ids),
                "n_became_critical": sum(1 for d in pair.task_deltas if d.became_critical),
                "n_recovered": sum(1 for d in pair.task_deltas if d.recovered),
                "n_logic_changes": sum(
                    len(d.predecessors_added) + len(d.predecessors_removed)
                    for d in pair.task_deltas
                ),
                "n_notable": len(notable),
                "top_changes": top,
            }
        )
    return views


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
        trends=_STATE.get("trends"),
        sra=_sra_view(_STATE.get("sra")),
        sra_note=_STATE.get("sra_note"),
        diffs=_diffs_view(_STATE.get("diffs") or ()),
        phases=_STATE.get("phases") or (),
        phases_note=_STATE.get("phases_note"),
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
        if len(uploads) > MAX_UPLOADS:
            return _render_page(
                error=(
                    f"Up to {MAX_UPLOADS} schedule files are supported per analysis; "
                    f"got {len(uploads)}."
                ),
                status=400,
            )
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
        build_excel_workbook(
            analysis,
            trends=_STATE.get("trends"),
            sra=_STATE.get("sra"),
            diff=_STATE.get("diffs") or (),
        ).save(buf)
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
        build_word_document(
            analysis,
            trends=_STATE.get("trends"),
            sra=_STATE.get("sra"),
            diff=_STATE.get("diffs") or (),
        ).save(buf)
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
