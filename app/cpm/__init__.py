"""Critical Path Method engine package."""

from __future__ import annotations

from app.cpm.engine import compute_cpm
from app.cpm.result import CPMResult, TaskTiming

__all__ = ["CPMResult", "TaskTiming", "compute_cpm"]
