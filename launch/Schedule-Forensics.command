#!/bin/bash
# Schedule Forensics — one-click launcher (macOS).
# Double-click this file (or a Finder ALIAS of it placed on your Desktop).
# First run sets up the environment; later runs just start the tool.
set -e

# ── Optional config — edit these if you like ────────────────────────────────
: "${SF_PORT:=5000}"                       # change if 5000 is busy (macOS AirPlay uses it)
# To use a LOCAL Qwen-class model for polished summaries, uncomment + point these
# at your local OpenAI-compatible server (llama.cpp / LM Studio / vLLM). Loopback only.
# export SF_LLM_BASE_URL="http://127.0.0.1:8080/v1"
# export SF_LLM_MODEL="qwen"
export SF_PORT

# ── Locate the repo (this script lives in <repo>/launch) ────────────────────
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

# ── First-run setup: virtualenv + install ──────────────────────────────────
if [ ! -x ".venv/bin/python" ]; then
  echo "First run: setting up the environment (this happens once)…"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi

# Build the native .mpp reader (MPXJ) on first run if Java + Maven are present. The
# importer auto-discovers tools/mpxj, so .mpp uploads then parse with no extra config.
# Best-effort: if it fails or the toolchain is absent, the other formats still work.
if [ ! -f "tools/mpxj/classes/MpxjToMspdi.class" ] \
   && command -v java >/dev/null 2>&1 && command -v mvn >/dev/null 2>&1; then
  echo "Setting up native .mpp support (MPXJ)… (one-time)"
  bash tools/mpxj/setup.sh \
    || echo "Note: MPXJ build failed; .mpp parsing unavailable (see docs/MPXJ.md)."
fi

URL="http://127.0.0.1:${SF_PORT}"
echo "Starting Schedule Forensics at ${URL}"
echo "(Close this window to stop the tool. All data stays on this machine.)"
# Open the browser a moment after the server starts.
( sleep 2; open "${URL}" >/dev/null 2>&1 || true ) &
exec .venv/bin/python -m schedule_forensics.webapp
