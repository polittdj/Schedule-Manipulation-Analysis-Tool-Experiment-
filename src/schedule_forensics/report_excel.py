"""Excel report generator for Schedule Forensics (openpyxl).

Public API
----------
``build_excel_workbook(analysis) -> Workbook``
    Build and return the workbook in memory (no disk I/O).

``build_excel_report(analysis, path) -> None``
    Build the workbook and write it to *path* as a ``.xlsx`` file.

Sheets
------
* **Summary** -- CUI banner; project finish (working-minute offset and working
  days = offset / 480.0); critical path ids; driving chain ids; health score;
  CPM error (if any).
* **DCMA** -- header row + 14 rows in id order. Columns: Metric ID, Name, Status,
  Measured, Threshold, Direction, Extension?, Source, Detail. Numeric measured /
  threshold are written as numbers; None -> blank.
* **Findings** -- one row per failing metric, or a "no failing metrics" note.

CUI / LAW 1: no schedule data leaves the machine; all writes are local. The
``CUI_NOTICE`` constant is the single source of truth (in every sheet).

Units: working-minute offsets are divided by 480.0 for working days. This is a
display-only conversion; analysis values are never recomputed -- we render
exactly what ``ScheduleAnalysis`` holds (H-DRIFT-1 / LAW 2). Note: openpyxl
round-trips a whole float (e.g. ``2.0``) back as ``int 2``; that is the value
2 working days either way.
"""

from __future__ import annotations

import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from schedule_forensics.analysis import ScheduleAnalysis
from schedule_forensics.metrics_common import MetricStatus

CUI_NOTICE: str = (
    "CONTROLLED UNCLASSIFIED INFORMATION (CUI) — generated locally; "
    "not for distribution. "
    "This report may contain CUI per NIST 800-171 / DFARS."
)

_MINUTES_PER_DAY: float = 480.0

_DCMA_HEADERS: list[str] = [
    "Metric ID",
    "Name",
    "Status",
    "Measured",
    "Threshold",
    "Direction",
    "Extension?",
    "Source",
    "Detail",
]


def _header_fill() -> PatternFill:
    return PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")


def _cui_fill() -> PatternFill:
    return PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")


def _status_fill(status: MetricStatus) -> PatternFill:
    if status is MetricStatus.PASS:
        return PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    if status is MetricStatus.FAIL:
        return PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    return PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")


def _add_cui_banner(ws: Worksheet, span: str) -> None:
    """Write the CUI banner across ``span`` (e.g. ``'A1:C1'``) on row 1."""
    cell = ws.cell(row=1, column=1, value=CUI_NOTICE)
    cell.font = Font(bold=True, color="FF0000")
    cell.fill = _cui_fill()
    ws.merge_cells(span)
    cell.alignment = Alignment(wrap_text=True)
    ws.row_dimensions[1].height = 32


def _autofit_columns(ws: Worksheet) -> None:
    """Expand each column to fit its widest content (approximate)."""
    for col_cells in ws.columns:
        first = col_cells[0]
        if first.column is None:
            continue
        col_letter = get_column_letter(first.column)
        max_len = max((len(str(c.value)) for c in col_cells if c.value is not None), default=0)
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 10), 80)


def _build_summary_sheet(ws: Worksheet, analysis: ScheduleAnalysis) -> None:
    _add_cui_banner(ws, "A1:C1")

    for col, header in enumerate(("Field", "Value", "Notes"), start=1):
        cell = ws.cell(row=2, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _header_fill()

    rows: list[tuple[str, object, str]] = []
    if analysis.project_finish is not None:
        rows.append(
            (
                "Project Finish (working minutes)",
                analysis.project_finish,
                "offset from project_start",
            )
        )
        rows.append(
            (
                "Project Finish (working days)",
                analysis.project_finish / _MINUTES_PER_DAY,
                "offset / 480.0",
            )
        )
    else:
        rows.append(("Project Finish (working minutes)", "n/a", "CPM could not be computed"))
        rows.append(("Project Finish (working days)", "n/a", "CPM could not be computed"))

    cp_str = ", ".join(str(uid) for uid in analysis.critical_path) or "(none)"
    rows.append(("Critical Path (UniqueIDs)", cp_str, "tasks with total_float <= 0, topo order"))
    dc_str = ", ".join(str(uid) for uid in analysis.driving_chain) or "(none)"
    rows.append(("Driving Chain (UniqueIDs)", dc_str, "binding-link back-trace to project finish"))

    if analysis.health_score is not None:
        rows.append(("Health Score", analysis.health_score, "% of runnable DCMA metrics that PASS"))
    else:
        rows.append(("Health Score", "n/a", "no runnable DCMA metrics"))

    if analysis.cpm_error:
        rows.append(("CPM Error", analysis.cpm_error, "CPM-dependent checks were SKIPPED"))

    for r_idx, (field, value, note) in enumerate(rows, start=3):
        ws.cell(row=r_idx, column=1, value=field)
        ws.cell(row=r_idx, column=2, value=value)
        ws.cell(row=r_idx, column=3, value=note)

    _autofit_columns(ws)


def _build_dcma_sheet(ws: Worksheet, analysis: ScheduleAnalysis) -> None:
    _add_cui_banner(ws, "A1:I1")

    for col, header in enumerate(_DCMA_HEADERS, start=1):
        cell = ws.cell(row=2, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _header_fill()

    for r_idx, metric in enumerate(analysis.dcma, start=3):
        values: list[object] = [
            metric.metric_id,
            metric.name,
            str(metric.status),
            metric.measured,  # float or None -> blank when None
            metric.threshold,
            "" if metric.direction is None else str(metric.direction),
            "Yes" if metric.is_extension else "No",
            metric.source,
            metric.detail,
        ]
        for col, val in enumerate(values, start=1):
            cell = ws.cell(row=r_idx, column=col, value=val)
            if col == 3:
                cell.fill = _status_fill(metric.status)

    _autofit_columns(ws)


def _build_findings_sheet(ws: Worksheet, analysis: ScheduleAnalysis) -> None:
    _add_cui_banner(ws, "A1:B1")

    hdr = ws.cell(row=2, column=1, value="Failing Metric")
    hdr.font = Font(bold=True, color="FFFFFF")
    hdr.fill = _header_fill()

    if analysis.findings:
        for r_idx, name in enumerate(analysis.findings, start=3):
            ws.cell(row=r_idx, column=1, value=name)
    else:
        ws.cell(row=3, column=1, value="no failing metrics").font = Font(italic=True)

    _autofit_columns(ws)


def build_excel_workbook(analysis: ScheduleAnalysis) -> Workbook:
    """Build and return an openpyxl ``Workbook`` (Summary / DCMA / Findings sheets)."""
    wb = Workbook()
    summary = wb.active
    assert summary is not None  # a fresh Workbook always has an active sheet
    summary.title = "Summary"
    _build_summary_sheet(summary, analysis)
    _build_dcma_sheet(wb.create_sheet("DCMA"), analysis)
    _build_findings_sheet(wb.create_sheet("Findings"), analysis)
    return wb


def build_excel_report(analysis: ScheduleAnalysis, path: str | os.PathLike[str]) -> None:
    """Write an Excel ``.xlsx`` report for *analysis* to *path* (all data stays local)."""
    build_excel_workbook(analysis).save(path)
