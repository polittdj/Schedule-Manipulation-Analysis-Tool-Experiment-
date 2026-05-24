#!/bin/bash
# SessionStart hook — bootstrap the local environment for Claude Code on the web so
# EVERY session can run the tool, its tests, and its linters with no manual setup.
#
# Two jobs:
#   1. Python virtualenv (.venv) + pinned dependencies (pydantic / flask / openpyxl /
#      python-docx, plus the dev tools pytest / ruff / mypy).
#   2. MPXJ — the Java-backed native ".mpp" reader — built into tools/mpxj/. The
#      importer AUTO-DISCOVERS that location (no env var needed), so ".mpp" uploads
#      parse out of the box. This is the piece that was missing in fresh sessions:
#      tools/mpxj/{lib,classes} are git-ignored build artifacts, so without this the
#      tool fails closed on every ".mpp" with "native .mpp parsing needs MPXJ".
#
# Idempotent and non-interactive (safe to re-run; fast once the container is cached).
# Never blocks the session: every step is best-effort and the hook always exits 0.
#
# LAW 1 (data sovereignty): this installs only PUBLIC build/runtime dependencies
# (pip packages; the MPXJ Java library from Maven Central). It reads, creates, and
# transmits NO schedule data.
set -uo pipefail  # deliberately not -e: a failed optional step must not block startup

# Web-only: local developers use the one-click launcher or docs/MPXJ.md. Drop this
# guard (or run with CLAUDE_CODE_REMOTE=true) to bootstrap local sessions too.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$REPO" || exit 0

# ── 1. Python venv + dependencies ─────────────────────────────────────────────
if [ ! -x ".venv/bin/python" ]; then
  echo "[session-start] creating .venv and installing dependencies ..."
  if python3 -m venv .venv \
    && .venv/bin/python -m pip install -q --upgrade pip \
    && .venv/bin/python -m pip install -q -e ".[dev]"; then
    echo "[session-start] dependencies installed."
  else
    echo "[session-start] WARNING: dependency install failed (see output above)." >&2
  fi
else
  echo "[session-start] .venv present; skipping dependency install."
fi

# Make the venv's python / pytest / ruff / mypy the default for this session's shells.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -x ".venv/bin/python" ]; then
  echo "export PATH=\"$REPO/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

# ── 2. MPXJ native ".mpp" reader (best-effort; auto-discovered by the importer) ─
if [ ! -f "tools/mpxj/classes/MpxjToMspdi.class" ]; then
  if command -v java >/dev/null 2>&1 && command -v mvn >/dev/null 2>&1; then
    echo "[session-start] building MPXJ (native .mpp reader) — first run only ..."
    if bash tools/mpxj/setup.sh; then
      echo "[session-start] MPXJ ready; native .mpp parsing enabled."
    else
      echo "[session-start] WARNING: MPXJ build failed; .mpp parsing unavailable" >&2
      echo "[session-start]          (the rest of the tool is unaffected; see docs/MPXJ.md)." >&2
    fi
  else
    echo "[session-start] NOTE: java and maven are not both on PATH; skipping MPXJ build." >&2
    echo "[session-start]       (native .mpp parsing needs them; see docs/MPXJ.md)." >&2
  fi
else
  echo "[session-start] MPXJ already built; native .mpp parsing enabled."
fi

echo "[session-start] environment ready."
exit 0
