"""MS Project (``.mpp``) parsing seam.

Real ``.mpp`` parsing requires MS Project COM automation (``win32com``) on Windows with MS
Project installed — none of which exist in this sandbox. This module therefore ships a
**stub** that raises ``NotImplementedError``. The function is the *seam*: in tests it is
monkeypatched with a synthetic-Schedule factory; a production build replaces the stub body
with a real adapter.

Parser contract (full text in ``docs/parser-contract.md``):
- Input: a filesystem ``Path`` to a ``.mpp`` file.
- Output: a fully-validated ``app.models.Schedule``. Task identity is ``unique_id``.
  Durations and lags are working-time minutes. The returned Schedule must satisfy all model
  invariants (unique ids, referential integrity), so downstream CPM/metrics can trust it.
"""

from __future__ import annotations

from pathlib import Path

from app.models import Schedule

_UNAVAILABLE_MESSAGE = (
    "Real .mpp parsing requires MS Project COM automation (win32com), which is not "
    "available in this environment. In tests, monkeypatch 'app.parsers.mpp.parse_mpp' with "
    "a synthetic-Schedule factory; a production build would supply a real adapter here."
)


def parse_mpp(file_path: Path) -> Schedule:
    """Parse an MS Project ``.mpp`` file into a Schedule.

    Stub: always raises ``NotImplementedError``. See module docstring for the contract.
    """
    raise NotImplementedError(_UNAVAILABLE_MESSAGE)
