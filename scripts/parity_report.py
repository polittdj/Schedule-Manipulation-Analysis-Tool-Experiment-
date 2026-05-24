"""CLI: run the golden-file parity harness and print a per-case report.

Usage::

    python scripts/parity_report.py [--root DIR]

*root* defaults to ``tests/fixtures/golden`` (the in-repo synthetic/self cases).
Point ``--root`` at a LOCAL directory outside the repo for REAL reference cases:
real schedule inputs are CUI and must never be committed (LAW 1). See
``docs/PARITY.md`` for the case format and how to add a reference-tool case.

Exit code is ``0`` when every check in every case is within tolerance, ``1`` on
any drift (or a malformed case), and ``2`` when no cases are found -- so this can
gate a local fidelity check without ever touching the network.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

# Allow running directly from a source checkout (no install needed), mirroring
# the pytest config's ``pythonpath = ["src"]``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from schedule_forensics.parity import (  # noqa: E402
    ParityError,
    discover_cases,
    evaluate_case,
    format_report,
    load_case,
)

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parity_report",
        description="Diff this tool's analysis against reference-tool golden cases (local only).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_DEFAULT_ROOT,
        help=f"Directory of golden cases (default: {_DEFAULT_ROOT}).",
    )
    args = parser.parse_args(argv)

    case_dirs = discover_cases(args.root)
    if not case_dirs:
        print(f"No golden cases found under {args.root}. See docs/PARITY.md to add one.")
        return 2

    all_ok = True
    for case_dir in case_dirs:
        try:
            case = load_case(case_dir)
            results = evaluate_case(case)
        except ParityError as exc:
            print(f"[ERROR] {case_dir}: {exc}")
            all_ok = False
            continue
        print(format_report(case, results))
        print()
        if not all(r.ok for r in results):
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
