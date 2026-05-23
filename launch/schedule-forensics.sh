#!/bin/bash
# Schedule Forensics — one-click launcher (Linux).
# Make executable (chmod +x) and double-click, or use the .desktop entry.
set -e

: "${SF_PORT:=5000}"
# To use a LOCAL Qwen-class model (llama.cpp / LM Studio / vLLM), uncomment + set
# (loopback only):
# export SF_LLM_BASE_URL="http://127.0.0.1:8080/v1"
# export SF_LLM_MODEL="qwen"
export SF_PORT

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

if [ ! -x ".venv/bin/python" ]; then
  echo "First run: setting up the environment (this happens once)…"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi

URL="http://127.0.0.1:${SF_PORT}"
echo "Starting Schedule Forensics at ${URL}"
echo "(Close this window / Ctrl-C to stop. All data stays on this machine.)"
( sleep 2; (xdg-open "${URL}" >/dev/null 2>&1 || true) ) &
exec .venv/bin/python -m schedule_forensics.webapp
