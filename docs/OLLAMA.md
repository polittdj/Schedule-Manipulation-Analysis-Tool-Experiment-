# Local LLM executive summaries via Ollama (optional, CUI-safe)

The executive summary is always built from a **deterministic factual narrative** —
every number traces to the analysis (H-DRIFT-1). A local LLM may only **rephrase**
that narrative into smoother prose; it can never add, remove, or alter a figure.
This is entirely optional: with no model the tool returns the factual narrative
verbatim (`NullInferenceBackend`).

## LAW 1 — why this is CUI-safe

The model runs **on your machine** and is reached over **loopback only**
(`127.0.0.1` / `localhost` / `::1`). `OllamaBackend` enforces this at construction
— a non-loopback host raises `ClassificationError` and refuses to run. No schedule
data ever leaves the machine. (The hard-gated cloud backend stays unreachable
under CUI; see `inference.py`.)

## One-time setup (on your machine)

1. **Install Ollama** — https://ollama.com/download (Windows/macOS/Linux).
   *(This dev environment's network policy blocks the Ollama download, so the
   integration here is verified against a faithful mocked server; you install the
   real app locally.)*
2. **Pull a model** — a small instruct model is plenty for rephrasing:
   ```sh
   ollama pull llama3.2          # ~2 GB; or llama3.2:1b (~1.3 GB) for low-RAM machines
   ```
3. **Make sure the server is running** — Ollama usually runs as a background
   service after install; otherwise start it with `ollama serve` (listens on
   `127.0.0.1:11434`).

## Turn it on for Schedule Forensics

Set one environment variable before launching the web app:

```sh
export SF_OLLAMA_MODEL=llama3.2          # the model you pulled
# optional, defaults to 127.0.0.1:11434 (loopback only):
export SF_OLLAMA_HOST=127.0.0.1:11434
python -m schedule_forensics.webapp
```

That's it — the executive summary on the dashboard (and in the Word/Excel reports)
will be rephrased by your local model. The one-click launcher (see the project
launcher docs) sets `SF_OLLAMA_MODEL` and starts Ollama for you automatically when
it is installed.

### Selecting a backend (precedence)

`backend_from_env()` chooses, in order (all local; a network backend is never
selected automatically):

1. `SF_LLM_BASE_URL` → `LocalOpenAIBackend` (any local OpenAI-compatible server:
   llama.cpp / LM Studio / vLLM, or Ollama's `/v1` endpoint).
2. `SF_OLLAMA_MODEL` → `OllamaBackend` (Ollama's native `/api/chat`).
3. neither → `NullInferenceBackend` (deterministic, no model).

## Behaviour & guarantees

- **Fail-safe:** if Ollama is not running, the model is not pulled, or it times
  out, the summary silently **falls back to the deterministic narrative** — the
  tool never errors out because of the LLM.
- **No number ever changes:** the system prompt instructs the model to preserve
  every figure exactly, and the authoritative numbers in the dashboard/reports are
  rendered straight from the analysis, not from the model's prose.
- **Determinism note:** LLM output is not bit-reproducible; the rephrased prose may
  vary run to run. The factual narrative underneath does not.
