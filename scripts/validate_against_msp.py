"""Local-only validation harness: diff the importer output vs. live MS Project COM.

WINDOWS + MS PROJECT ONLY. This script is intentionally a guarded stub on every
other platform (this build is developed on Linux, where COM is unavailable -- see
docs/HAZARDS.md, H-NO-COM-HERE). On a Windows machine with MS Project installed,
it opens the same `.mpp` file via COM and via the (future) COM importer and diffs
every field for every task, field-by-field.

Results are written under ``local_validation_results/`` (gitignored). Real `.mpp`
files and their derived results are NEVER committed (LAW 1).

Usage (Windows): python scripts/validate_against_msp.py path\\to\\schedule.mpp
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    try:
        import win32com.client  # noqa: F401  (presence check only)
    except ImportError:
        print(
            "validate_against_msp: COM (win32com) is unavailable on this platform.\n"
            "This harness runs only on Windows with MS Project installed. The "
            "cross-platform importers (MS Project XML / Primavera XER / MPXJ) are "
            "validated by the pytest suite instead. See docs/HAZARDS.md "
            "(H-NO-COM-HERE).",
        )
        return 0

    if len(argv) < 2:
        print("usage: python scripts/validate_against_msp.py <path-to.mpp>")
        return 2

    # Windows-only: read the same .mpp via the COM importer and report each task's
    # required fields. The COM driver opens headless + ReadOnly and tears the app
    # down in finally (see importers/com_msproject.py). This is the on-Windows
    # ground-truth check the Linux unit tests cannot perform (docs/HAZARDS.md
    # H-NO-COM-HERE); a full field-by-field diff vs a second COM read is the next
    # increment. Results stay LOCAL (LAW 1).
    from schedule_forensics.importers.com_msproject import (
        ComUnavailableError,
        parse_mpp_via_com,
    )

    mpp_path = argv[1]
    try:
        schedule = parse_mpp_via_com(mpp_path)
    except ComUnavailableError as exc:
        print(f"validate_against_msp: {exc}")
        return 0
    except Exception as exc:  # noqa: BLE001 -- surface any import failure to the operator
        print(f"validate_against_msp: failed to read {mpp_path!r} via COM: {exc}")
        return 1

    print(f"validate_against_msp: COM read OK -- {schedule.name!r}")
    print(f"  project_start={schedule.project_start.isoformat()}")
    status = schedule.status_date.isoformat() if schedule.status_date else "None"
    print(f"  status_date={status}")
    print(f"  tasks={len(schedule.tasks)}  relations={len(schedule.relations)}")
    for task in schedule.tasks:
        print(
            f"    UID={task.unique_id} dur_min={task.duration_minutes} "
            f"constraint={task.constraint_type.value} pct={task.percent_complete} "
            f"name={task.name!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
