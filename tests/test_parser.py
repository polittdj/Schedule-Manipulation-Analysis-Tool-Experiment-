"""M3: the parser seam — the stub raises clearly, and the seam is monkeypatchable."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import Schedule
from app.parsers import mpp, parse_schedule
from tests.conftest import make_schedule


def test_parse_mpp_stub_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError) as excinfo:
        mpp.parse_mpp(Path("schedule.mpp"))
    assert "Save As" in str(excinfo.value)  # points users to the XML export path


def test_parse_schedule_dispatches_through_monkeypatched_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic = make_schedule()

    def fake_parse(file_path: Path) -> Schedule:
        return synthetic

    monkeypatch.setattr(mpp, "parse_mpp", fake_parse)
    result = parse_schedule(Path("anything.mpp"))
    assert result is synthetic
    assert isinstance(result, Schedule)


def test_parse_schedule_rejects_unknown_extension() -> None:
    with pytest.raises(NotImplementedError):
        parse_schedule(Path("schedule.docx"))  # .xml/.xer/.json/.mpp are handled; .docx is not
