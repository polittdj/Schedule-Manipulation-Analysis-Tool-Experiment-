#!/bin/bash
# Double-click this file (macOS / Linux) to start the Schedule Manipulation Analysis Tool.
# It opens in your web browser. Close the Terminal window it opens to stop the tool.

cd "$(dirname "$0")" || exit 1

# First run only: build the local environment and install the tool's parts.
if [ ! -d ".venv" ]; then
  echo "First-time setup - this takes about a minute..."
  if command -v python3.13 >/dev/null 2>&1; then PY=python3.13; else PY=python3; fi
  "$PY" -m venv .venv || { echo "Could not create the environment. Install Python 3.13 first."; read -r _; exit 1; }
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt || { echo "Install failed."; read -r _; exit 1; }
  # Optional: native .mpp reading via MPXJ (needs Java). Best-effort — the app runs fine without it.
  ./.venv/bin/python -m pip install --quiet -r requirements-mpp.txt 2>/dev/null || true
fi

./.venv/bin/python launch.py
