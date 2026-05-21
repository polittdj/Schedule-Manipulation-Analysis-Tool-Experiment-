"""Schedule parsers and the monkeypatchable parsing seam."""

from __future__ import annotations

from pathlib import Path

from app.models import Schedule
from app.parsers import mpp
from app.parsers.msp_xml import parse_msp_xml
from app.parsers.xer import parse_xer

__all__ = ["parse_schedule"]

SUPPORTED_SUFFIXES = (".xml", ".xer", ".mpp", ".json")


def parse_schedule(file_path: Path) -> Schedule:
    """Dispatch to a format-specific parser based on the file extension.

    - ``.xml``  -> MS Project XML (best-effort)
    - ``.xer``  -> Primavera P6 export (best-effort)
    - ``.json`` -> the tool's own Schedule JSON
    - ``.mpp``  -> raises (binary; use "Save As -> XML" instead)

    ``.mpp`` resolves ``mpp.parse_mpp`` at call time so tests can monkeypatch the seam.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".xml":
        return parse_msp_xml(file_path)
    if suffix == ".xer":
        return parse_xer(file_path)
    if suffix == ".json":
        return Schedule.model_validate_json(file_path.read_bytes())
    if suffix == ".mpp":
        return mpp.parse_mpp(file_path)
    supported = ", ".join(SUPPORTED_SUFFIXES)
    raise NotImplementedError(f"No parser for '{suffix}' files. Supported: {supported}.")
