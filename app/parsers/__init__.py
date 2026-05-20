"""Schedule parsers and the monkeypatchable parsing seam."""

from __future__ import annotations

from pathlib import Path

from app.models import Schedule
from app.parsers import mpp

__all__ = ["parse_schedule"]


def parse_schedule(file_path: Path) -> Schedule:
    """Dispatch to a format-specific parser based on the file extension.

    Dispatch resolves ``mpp.parse_mpp`` at call time, so a test that monkeypatches
    ``app.parsers.mpp.parse_mpp`` with a synthetic-Schedule factory takes effect here too.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".mpp":
        return mpp.parse_mpp(file_path)
    raise NotImplementedError(f"No parser is registered for '{suffix}' files (supported: .mpp).")
