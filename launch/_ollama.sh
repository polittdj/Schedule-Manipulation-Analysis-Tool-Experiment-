#!/bin/bash
# Sourced by the macOS/Linux launchers. Manages a local Ollama for the tool's
# session:
#   • on launch — auto-detect Ollama, start the server if it isn't already up, and
#     select an already-pulled model so the executive summary is AI-polished;
#   • on exit  — unload the model (frees memory) and, IF this launcher started the
#     server, stop it. A pre-existing system Ollama (a managed service / menu-bar
#     app) is left running, since the tool did not start it.
#
# For the exit hook to run, the launcher must NOT `exec` the web app (so this
# shell regains control and its EXIT trap fires).
#
# CUI-safe (LAW 1): Ollama serves on loopback (127.0.0.1) only and the tool's
# OllamaBackend refuses any non-loopback host. NOTHING is auto-downloaded — with
# no Ollama (or no pulled model) the tool falls back to its deterministic summary.
# Override the model by exporting SF_OLLAMA_MODEL before launch. See docs/OLLAMA.md.

SF_OLLAMA_STARTED=""
SF_OLLAMA_SERVE_PID=""

sf_setup_ollama() {
  command -v ollama >/dev/null 2>&1 || return 0

  # Start the local server if it is not already responding. Keep it as a child of
  # this shell (not a detached subshell) so we can stop exactly it on exit.
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ollama serve >/dev/null 2>&1 &
    SF_OLLAMA_SERVE_PID=$!
    SF_OLLAMA_STARTED=1
    sleep 1
  fi

  # Use SF_OLLAMA_MODEL if the user set one; otherwise the first already-pulled
  # model. Never auto-pull (that is a large, surprising download).
  if [ -z "${SF_OLLAMA_MODEL:-}" ]; then
    SF_OLLAMA_MODEL="$(ollama list 2>/dev/null | awk 'NR==2 {print $1; exit}' || true)"
  fi

  if [ -n "${SF_OLLAMA_MODEL:-}" ]; then
    export SF_OLLAMA_MODEL
    echo "AI summaries: ON (local Ollama model: ${SF_OLLAMA_MODEL})."
  else
    echo "Ollama is installed but no model is pulled — using deterministic summaries."
    echo "  Run 'ollama pull llama3.2' once to enable AI-polished summaries."
  fi
}

sf_stop_ollama() {
  trap - EXIT INT TERM HUP  # disarm so Ctrl-C (INT then EXIT) cannot run this twice
  command -v ollama >/dev/null 2>&1 || return 0
  # Unload the model from memory (frees the GBs); harmless if already unloaded.
  if [ -n "${SF_OLLAMA_MODEL:-}" ]; then
    ollama stop "$SF_OLLAMA_MODEL" >/dev/null 2>&1 || true
  fi
  # Stop the server only if THIS launcher started it (don't fight a system Ollama).
  if [ "${SF_OLLAMA_STARTED:-}" = "1" ] && [ -n "${SF_OLLAMA_SERVE_PID:-}" ]; then
    kill "$SF_OLLAMA_SERVE_PID" >/dev/null 2>&1 || true
    echo "Ollama: stopped the server this launcher started."
  fi
}

sf_setup_ollama
# Run the cleanup when the launcher shell exits (normal exit, Ctrl-C, window close).
trap sf_stop_ollama EXIT INT TERM HUP
