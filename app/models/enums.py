"""Enumerations shared across the data model and the metrics layer."""

from __future__ import annotations

from enum import StrEnum


class RelationType(StrEnum):
    """Precedence relationship types (predecessor -> successor)."""

    FS = "FS"  # Finish-to-Start
    SS = "SS"  # Start-to-Start
    FF = "FF"  # Finish-to-Finish
    SF = "SF"  # Start-to-Finish


class Severity(StrEnum):
    """Metric outcome severity. Exactly three states — no ERROR, no fourth state.

    A metric that cannot run raises rather than returning a fabricated result.
    """

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class Direction(StrEnum):
    """Direction of a threshold comparison: the value passes when it is at most /
    at least the threshold."""

    AT_MOST = "<="
    AT_LEAST = ">="
