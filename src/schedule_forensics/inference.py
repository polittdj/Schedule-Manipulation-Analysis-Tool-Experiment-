"""Pluggable inference backend for the executive summary (LAW 1 routing).

The executive summary is built from a deterministic FACTUAL narrative (every
number traces to the analysis -- H-DRIFT-1); a backend may only *rephrase* that
text, never invent numbers. Backends are selected through :func:`select_backend`,
which enforces data sovereignty (LAW 1): a non-local (network) backend is
**structurally unselectable** under any non-UNCLASSIFIED classification.

Backends
--------
* :class:`NullInferenceBackend` -- the DEFAULT. No model, fully local,
  deterministic (returns the factual narrative unchanged). The whole tool works
  and is testable with zero model present.
* :class:`OllamaBackend` -- local Ollama (CUI-safe). Its actual model call is the
  Phase-7 human-in-loop wiring step (not wired here); ``summarize`` raises until
  then. It is ``is_local = True`` so it is reachable under CUI.
* :class:`UnclassifiedClaudeBackend` -- NETWORK. ``is_local = False``. Usable only
  when classification is explicitly ``UNCLASSIFIED``; hard-gated off by default
  and never reachable under CUI (see :func:`select_backend`).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit


class Classification(StrEnum):
    """Data classification governing inference routing. Default is CUI."""

    CUI = "CUI"
    UNCLASSIFIED = "UNCLASSIFIED"


DEFAULT_CLASSIFICATION = Classification.CUI


class InferenceError(RuntimeError):
    """A backend could not produce a summary."""


class ClassificationError(InferenceError):
    """Routing schedule data to a forbidden backend for the classification (LAW 1)."""


@runtime_checkable
class InferenceBackend(Protocol):
    """Rephrases a factual narrative. ``is_local`` is False iff it leaves the machine."""

    name: str
    is_local: bool

    def summarize(self, narrative: str) -> str: ...


class NullInferenceBackend:
    """Default, local, deterministic: returns the factual narrative unchanged.

    This is what makes the executive summary (and the whole tool) testable with no
    model. It performs no network or filesystem I/O.
    """

    name = "null"
    is_local = True

    def summarize(self, narrative: str) -> str:
        return narrative


class OllamaBackend:
    """Local Ollama backend (CUI-safe). Wiring is the Phase-7 human checkpoint.

    Constructing it is fine; the actual local model call is deferred. Until wired,
    ``summarize`` raises rather than silently returning a non-summary.
    """

    name = "ollama"
    is_local = True

    def __init__(self, model: str = "llama3:8b", host: str = "127.0.0.1:11434") -> None:
        self.model = model
        self.host = host

    def summarize(self, narrative: str) -> str:
        raise InferenceError(
            "OllamaBackend is not wired yet (Phase-7 human-in-loop model setup). "
            "Use NullInferenceBackend until the local model is connected."
        )


class UnclassifiedClaudeBackend:
    """NETWORK backend usable ONLY under explicit UNCLASSIFIED classification.

    ``is_local = False`` ensures :func:`select_backend` refuses it under CUI. Its
    network call is intentionally not wired here; even when wired it must remain
    structurally unreachable under any CUI classification (LAW 1).
    """

    name = "unclassified-claude"
    is_local = False

    def summarize(self, narrative: str) -> str:
        raise InferenceError(
            "UnclassifiedClaudeBackend is not wired and is only ever permitted for "
            "explicitly UNCLASSIFIED data (LAW 1)."
        )


# Only these hosts are accepted for a "local" LLM server: the model must run on
# THIS machine so no schedule data leaves it (LAW 1). Enforced at construction.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# The model's ONLY job is to rephrase the already-factual narrative. It must not
# alter any figure; the authoritative numbers live in the analysis/reports (the
# reports and dashboard render analysis fields directly, not this prose).
_REPHRASE_SYSTEM = (
    "You are a forensic scheduling analyst. Rephrase the following factual schedule "
    "analysis into a clear, professional executive narrative. Do NOT add, remove, or "
    "alter ANY number, date, percentage, task ID, or stated fact -- preserve every "
    "figure exactly as written. Output only the narrative prose, no preamble."
)


def _require_loopback(base_url: str) -> str:
    """Return ``base_url`` iff its host is loopback, else raise (fail closed, LAW 1)."""
    host = urlsplit(base_url).hostname
    if host is None or host.lower() not in _LOOPBACK_HOSTS:
        raise ClassificationError(
            f"LocalOpenAIBackend base_url host {host!r} is not loopback; only "
            "127.0.0.1/localhost/::1 is allowed so CUI schedule data never leaves the "
            "machine (LAW 1)."
        )
    return base_url


class LocalOpenAIBackend:
    """Rephrase via a LOCAL OpenAI-compatible model server (CUI-safe).

    Talks to ``{base_url}/chat/completions`` -- the API exposed by llama.cpp's
    ``llama-server``, LM Studio, vLLM, and Ollama -- so it runs any locally served
    model (built for a Qwen-class GGUF such as 32B Q4_K_M, but model-agnostic).
    The base URL host MUST be loopback (enforced in ``__init__`` via
    :func:`_require_loopback`), so ``is_local = True`` is truthful and the backend
    is reachable under CUI while structurally unable to egress.

    The model only rephrases the deterministic narrative; it never sources numbers
    (H-DRIFT-1). Uses the standard library only (no new dependency); the single
    network call is to loopback.
    """

    name = "local-openai"
    is_local = True

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080/v1",
        model: str = "qwen2.5-32b-instruct-q4_k_m",
        *,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = _require_loopback(base_url).rstrip("/")
        self.model = model
        self.timeout = timeout

    def summarize(self, narrative: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _REPHRASE_SYSTEM},
                    {"role": "user", "content": narrative},
                ],
                "temperature": 0.2,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise InferenceError(
                f"local model server not reachable at {self.base_url} ({exc}). Start your "
                "local OpenAI-compatible server (llama.cpp / LM Studio / vLLM), or use "
                "NullInferenceBackend."
            ) from exc
        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise InferenceError(f"unexpected response from local model server: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise InferenceError("local model server returned an empty completion")
        return content


def select_backend(classification: Classification, backend: InferenceBackend) -> InferenceBackend:
    """Return ``backend`` if the classification permits it, else raise (fail closed).

    A non-local backend is permitted ONLY under ``UNCLASSIFIED``. Under CUI (the
    default), any non-local backend raises :class:`ClassificationError` -- no
    schedule data may reach a network backend (LAW 1).
    """
    if not backend.is_local and classification is not Classification.UNCLASSIFIED:
        raise ClassificationError(
            f"backend {backend.name!r} is non-local; routing {classification} schedule "
            "data off-machine is forbidden (LAW 1). Use a local backend."
        )
    return backend


# Environment knobs for the local OpenAI-compatible model server.
LLM_BASE_URL_ENV = "SF_LLM_BASE_URL"  # e.g. http://127.0.0.1:8080/v1 (loopback only)
LLM_MODEL_ENV = "SF_LLM_MODEL"  # e.g. qwen2.5-32b-instruct-q4_k_m
_DEFAULT_LLM_MODEL = "qwen2.5-32b-instruct-q4_k_m"


def backend_from_env(env: Mapping[str, str] | None = None) -> InferenceBackend:
    """Pick a backend from the environment -- LAW 1 safe, default deterministic.

    If ``SF_LLM_BASE_URL`` is set, return a :class:`LocalOpenAIBackend` pointed at
    it (the host is loopback-enforced by the backend; a non-local URL raises) with
    ``SF_LLM_MODEL`` (default a Qwen-class GGUF name). Otherwise return the
    deterministic :class:`NullInferenceBackend`. A network backend is NEVER selected
    automatically -- that stays an explicit, UNCLASSIFIED-only choice.
    """
    source = os.environ if env is None else env
    base_url = source.get(LLM_BASE_URL_ENV)
    if not base_url:
        return NullInferenceBackend()
    model = source.get(LLM_MODEL_ENV) or _DEFAULT_LLM_MODEL
    return LocalOpenAIBackend(base_url=base_url, model=model)
