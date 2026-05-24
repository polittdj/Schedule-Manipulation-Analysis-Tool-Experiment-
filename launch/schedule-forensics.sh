#!/bin/bash
# Schedule Forensics — one-click launcher (Linux).
# Make executable (chmod +x) and double-click, or use the .desktop entry.
set -e

: "${SF_PORT:=5000}"
# Optional local AI-polished executive summaries (all loopback-only, CUI-safe):
#  • Easiest: install Ollama (https://ollama.com) and run 'ollama pull llama3.2' once;
#    this launcher then auto-starts Ollama and uses it. Override with SF_OLLAMA_MODEL.
#  • Or point at any local OpenAI-compatible server:
#    # export SF_LLM_BASE_URL="http://127.0.0.1:8080/v1"; export SF_LLM_MODEL="qwen"
export SF_PORT

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

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

# Optional local AI summaries via Ollama (auto-detected; CUI-safe). See docs/OLLAMA.md.
. "$REPO/launch/_ollama.sh"

URL="http://127.0.0.1:${SF_PORT}"
echo "Starting Schedule Forensics at ${URL}"
echo "(Close this window / Ctrl-C to stop. All data stays on this machine.)"
( sleep 2; (xdg-open "${URL}" >/dev/null 2>&1 || true) ) &
# NOT exec: keep this shell alive so the _ollama.sh EXIT trap can stop Ollama.
.venv/bin/python -m schedule_forensics.webapp
