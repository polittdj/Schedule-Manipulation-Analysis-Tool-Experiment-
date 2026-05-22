"""Word report generator for Schedule Forensics (python-docx).

Public API
----------
``build_word_document(analysis) -> Document``
    Build and return the document in memory (no disk I/O). Tests use this to
    inspect the output without writing to disk.

``build_word_report(analysis, path) -> None``
    Build the document and write it to *path* as a ``.docx`` file.

Document structure
------------------
1. Title paragraph: "Schedule Forensics Report"
2. CUI banner paragraph (the ``CUI_NOTICE`` constant, bold/highlighted).
3. Executive metrics section: project finish (offset + working days), health
   score, critical path ids, driving chain ids, CPM error (if present).
4. DCMA 14-Point table: header row + one row per metric in id order.
5. Findings list: one bullet per failing metric, or a "no failing metrics" note.
6. If any metric has ``is_extension=True``, a footnote distinguishing those rows
   as tool-original extensions (parity-honesty).

CUI / LAW 1: no schedule data leaves the machine; all writes are to the
caller-supplied local path. ``CUI_NOTICE`` is the single source of truth here.

Units: working-minute offsets are divided by 480.0 for the working-day display
value; analysis values are never recomputed -- we render exactly what
``ScheduleAnalysis`` holds (H-DRIFT-1 / LAW 2). python-docx's ``Document`` symbol
is a FACTORY; the type is ``docx.document.Document`` (imported for annotations,
constructed via ``docx.Document()``).
"""

from __future__ import annotations

import os
from typing import Any

import docx
from docx.document import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

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


def _set_cell_bg(cell: Any, hex_color: str) -> None:
    """Set a table cell's background fill to *hex_color* (e.g. ``'C6EFCE'``)."""
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def _status_color(status: MetricStatus) -> str:
    if status is MetricStatus.PASS:
        return "C6EFCE"  # light green
    if status is MetricStatus.FAIL:
        return "FFC7CE"  # light red
    return "FFEB9C"  # light yellow (SKIPPED)


def _add_title(doc: Document) -> None:
    title = doc.add_heading("Schedule Forensics Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _add_cui_banner(doc: Document) -> None:
    """Add the CUI notice as a visually distinct paragraph."""
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(CUI_NOTICE)
    run.bold = True
    run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
    run.font.size = Pt(10)
    p_pr = para._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "FFFF00")
    p_pr.append(shd)


def _add_executive_metrics(doc: Document, analysis: ScheduleAnalysis) -> None:
    doc.add_heading("Executive Metrics", level=1)

    def _row(label: str, value: object) -> None:
        para = doc.add_paragraph(style="List Bullet")
        run_label = para.add_run(f"{label}: ")
        run_label.bold = True
        para.add_run(str(value))

    if analysis.project_finish is not None:
        _row("Project Finish (working minutes)", analysis.project_finish)
        _row("Project Finish (working days)", f"{analysis.project_finish / _MINUTES_PER_DAY:.2f}")
    else:
        _row("Project Finish", "n/a (CPM could not be computed)")

    if analysis.health_score is not None:
        _row("Health Score", f"{analysis.health_score:.2f}%")
    else:
        _row("Health Score", "n/a (no runnable DCMA metrics)")

    cp_str = ", ".join(str(uid) for uid in analysis.critical_path) or "(none)"
    _row("Critical Path (UniqueIDs)", cp_str)
    dc_str = ", ".join(str(uid) for uid in analysis.driving_chain) or "(none)"
    _row("Driving Chain (UniqueIDs)", dc_str)

    if analysis.cpm_error:
        _row("CPM Error", analysis.cpm_error)


def _add_dcma_table(doc: Document, analysis: ScheduleAnalysis) -> None:
    doc.add_heading("DCMA 14-Point Assessment", level=1)

    table = doc.add_table(rows=1 + len(analysis.dcma), cols=len(_DCMA_HEADERS))
    table.style = "Table Grid"

    hdr_row = table.rows[0]
    for col_idx, header in enumerate(_DCMA_HEADERS):
        cell = hdr_row.cells[col_idx]
        para = cell.paragraphs[0]
        para.clear()
        run = para.add_run(header)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _set_cell_bg(cell, "4472C4")

    for row_idx, metric in enumerate(analysis.dcma, start=1):
        measured_str = "" if metric.measured is None else f"{metric.measured}"
        threshold_str = "" if metric.threshold is None else f"{metric.threshold}"
        direction_str = "" if metric.direction is None else str(metric.direction)
        values = [
            metric.metric_id,
            metric.name,
            str(metric.status),
            measured_str,
            threshold_str,
            direction_str,
            "Yes" if metric.is_extension else "No",
            metric.source,
            metric.detail,
        ]
        row = table.rows[row_idx]
        for col_idx, val in enumerate(values):
            cell = row.cells[col_idx]
            cell.text = val
            if col_idx == 2:
                _set_cell_bg(cell, _status_color(metric.status))


def _add_findings(doc: Document, analysis: ScheduleAnalysis) -> None:
    doc.add_heading("Findings (Failing Metrics)", level=1)
    if analysis.findings:
        for name in analysis.findings:
            doc.add_paragraph(name, style="List Bullet")
    else:
        run = doc.add_paragraph().add_run("no failing metrics")
        run.italic = True


def _add_extension_footnote(doc: Document, analysis: ScheduleAnalysis) -> None:
    extension_ids = [m.metric_id for m in analysis.dcma if m.is_extension]
    if not extension_ids:
        return
    doc.add_heading("Tool-Original Extensions", level=2)
    run = doc.add_paragraph().add_run(
        f"The following metrics ({', '.join(extension_ids)}) are tool-original extensions: "
        "capabilities beyond what Acumen Fuse, Steelray/SSI, or Microsoft Project produce "
        "natively. They are labeled 'Yes' in the Extension? column and must not be presented "
        "as reference-tool parity (parity-honesty rule -- CLAUDE.md)."
    )
    run.italic = True


def build_word_document(analysis: ScheduleAnalysis) -> Document:
    """Build and return a python-docx ``Document`` from *analysis* (no disk I/O)."""
    doc = docx.Document()
    _add_title(doc)
    _add_cui_banner(doc)
    _add_executive_metrics(doc, analysis)
    _add_dcma_table(doc, analysis)
    _add_findings(doc, analysis)
    _add_extension_footnote(doc, analysis)
    return doc


def build_word_report(analysis: ScheduleAnalysis, path: str | os.PathLike[str]) -> None:
    """Write a Word ``.docx`` report for *analysis* to *path* (all data stays local)."""
    build_word_document(analysis).save(os.fspath(path))
