"""End-to-end spine proof: MSPDI file -> Schedule -> CPM, asserted vs a hand calc.

This is the smallest test that exercises every layer of the trust-root spine and
fails the way the product fails (a wrong number), so it is the session's core
fidelity gate (LAW 2).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from schedule_forensics.analysis import analyze_schedule
from schedule_forensics.cpm import compute_cpm, offset_to_datetime
from schedule_forensics.importers.msp_xml import parse_msp_xml
from schedule_forensics.importers.xer import parse_xer

FIXTURE = Path(__file__).parent / "fixtures" / "msp_xml" / "simple_network.xml"
XER_FIXTURE = Path(__file__).parent / "fixtures" / "xer" / "simple_network.xer"


def test_xml_to_cpm_matches_hand_calc() -> None:
    schedule = parse_msp_xml(FIXTURE)
    result = compute_cpm(schedule)

    # Hand calc (480 min/day): A 0..960, B 960..2400, C 960..1440 (+960 slack), D ms @2400.
    assert (result.timings[1].early_start, result.timings[1].early_finish) == (0, 960)
    assert (result.timings[2].early_start, result.timings[2].early_finish) == (960, 2400)
    assert result.timings[3].total_float == 960
    assert result.timings[3].is_critical is False
    assert result.timings[4].early_finish == 2400
    assert result.project_finish == 2400
    assert result.critical_path == (1, 2, 4)

    # 5 working days from Mon 2025-01-06 08:00 -> Fri 2025-01-10 16:00 (no weekend crossed).
    finish = offset_to_datetime(schedule.project_start, result.project_finish, schedule.calendar)
    assert finish == dt.datetime(2025, 1, 10, 16)


def test_xer_and_mspdi_yield_equivalent_full_analysis() -> None:
    """The XER and MSPDI fixtures describe the same network, so the FULL analysis
    (CPM + DCMA-14 + driving path + health) must be identical via either importer
    -- proving XER is a drop-in for MSPDI through the whole stack, not just at the
    Schedule level (test_importer_xer covers the Schedule-level parity)."""
    msp = analyze_schedule(parse_msp_xml(FIXTURE))
    xer = analyze_schedule(parse_xer(XER_FIXTURE))

    assert msp.project_finish == xer.project_finish == 2400
    assert msp.critical_path == xer.critical_path == (1, 2, 4)
    assert msp.driving_chain == xer.driving_chain
    assert msp.health_score == xer.health_score
    # Every DCMA metric resolves to the same id + status via either importer.
    assert [(m.metric_id, m.status) for m in msp.dcma] == [
        (m.metric_id, m.status) for m in xer.dcma
    ]
