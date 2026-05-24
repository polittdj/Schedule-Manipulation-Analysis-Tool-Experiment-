"""Tests for OllamaBackend + backend_from_env Ollama routing (LAW 1 loopback-only).

The HTTP call is mocked, so these run with no Ollama server installed (the
environment here cannot install one). The key LAW-1 test is that a non-loopback
host is refused at construction (fail closed), and the key integration test is
that the executive summary falls back to the deterministic narrative when Ollama
is unreachable -- so the tool never errors out the user.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from schedule_forensics.analysis import analyze_schedule
from schedule_forensics.exec_summary import generate_executive_summary
from schedule_forensics.inference import (
    Classification,
    ClassificationError,
    InferenceError,
    LocalOpenAIBackend,
    NullInferenceBackend,
    OllamaBackend,
    backend_from_env,
    select_backend,
)
from schedule_forensics.schemas import Relation, Schedule, Task

_URLOPEN = "schedule_forensics.inference.urllib.request.urlopen"


def _fake_urlopen(body: bytes) -> MagicMock:
    """A context-manager mock whose ``.read()`` returns ``body`` (mimics urlopen)."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    return cm


def _chat_body(content: str) -> bytes:
    """Ollama native /api/chat response shape."""
    return json.dumps({"message": {"role": "assistant", "content": content}, "done": True}).encode()


# --- LAW 1: loopback enforcement (fail closed) ---
def test_rejects_non_loopback_host() -> None:
    with pytest.raises(ClassificationError, match="loopback"):
        OllamaBackend(host="evil.example.com:11434")


def test_accepts_loopback_hosts() -> None:
    assert OllamaBackend(host="127.0.0.1:11434").is_local is True
    assert OllamaBackend(host="localhost:11434").is_local is True


def test_cui_allows_ollama_backend() -> None:
    # is_local=True so the CUI router permits it (it cannot reach off-machine).
    assert select_backend(Classification.CUI, OllamaBackend()).name == "ollama"


# --- summarize() behaviour (HTTP mocked) ---
def test_summarize_returns_model_content() -> None:
    backend = OllamaBackend(model="llama3.2")
    with patch(_URLOPEN, return_value=_fake_urlopen(_chat_body("Polished narrative."))):
        assert backend.summarize("factual narrative") == "Polished narrative."


def test_summarize_posts_to_api_chat_with_model_and_narrative() -> None:
    backend = OllamaBackend(model="llama3.2:1b")
    captured: dict[str, Any] = {}

    def _capture(request: Any, *args: Any, **kwargs: Any) -> MagicMock:
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        return _fake_urlopen(_chat_body("ok"))

    with patch(_URLOPEN, side_effect=_capture):
        backend.summarize("THE NARRATIVE TEXT")
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["payload"]["model"] == "llama3.2:1b"
    assert captured["payload"]["stream"] is False
    # the narrative is sent verbatim as the user message (model only rephrases it)
    assert any("THE NARRATIVE TEXT" in m["content"] for m in captured["payload"]["messages"])


def test_summarize_unreachable_raises_clear_error() -> None:
    backend = OllamaBackend()
    with (
        patch(_URLOPEN, side_effect=urllib.error.URLError("connection refused")),
        pytest.raises(InferenceError, match="not reachable"),
    ):
        backend.summarize("x")


def test_summarize_malformed_response_raises() -> None:
    backend = OllamaBackend()
    with (
        patch(_URLOPEN, return_value=_fake_urlopen(b'{"no":"message here"}')),
        pytest.raises(InferenceError, match="unexpected response"),
    ):
        backend.summarize("x")


def test_summarize_empty_completion_raises() -> None:
    backend = OllamaBackend()
    with (
        patch(_URLOPEN, return_value=_fake_urlopen(_chat_body("   "))),
        pytest.raises(InferenceError, match="empty"),
    ):
        backend.summarize("x")


# --- backend_from_env factory ---
def test_env_ollama_model_selects_ollama() -> None:
    backend = backend_from_env({"SF_OLLAMA_MODEL": "llama3.2"})
    assert isinstance(backend, OllamaBackend)
    assert backend.model == "llama3.2"
    assert backend.base_url == "http://127.0.0.1:11434"


def test_env_ollama_host_override() -> None:
    backend = backend_from_env({"SF_OLLAMA_MODEL": "llama3.2", "SF_OLLAMA_HOST": "localhost:1234"})
    assert isinstance(backend, OllamaBackend)
    assert backend.base_url == "http://localhost:1234"


def test_env_llm_base_url_takes_precedence_over_ollama() -> None:
    backend = backend_from_env(
        {"SF_LLM_BASE_URL": "http://127.0.0.1:8080/v1", "SF_OLLAMA_MODEL": "llama3.2"}
    )
    assert isinstance(backend, LocalOpenAIBackend)


def test_env_neither_returns_null() -> None:
    assert isinstance(backend_from_env({}), NullInferenceBackend)


def test_env_ollama_non_loopback_host_fails_closed() -> None:
    with pytest.raises(ClassificationError):
        backend_from_env({"SF_OLLAMA_MODEL": "llama3.2", "SF_OLLAMA_HOST": "10.0.0.5:11434"})


# --- executive-summary integration (the real wiring point) ---
def _tiny_analysis() -> Any:
    sched = Schedule(
        name="Ollama wiring",
        project_start=dt.datetime(2025, 1, 6, 8),
        status_date=dt.datetime(2025, 1, 6, 8),
        tasks=(
            Task(unique_id=1, name="A", duration_minutes=480),
            Task(unique_id=2, name="B", duration_minutes=480),
        ),
        relations=(Relation(predecessor_id=1, successor_id=2),),
    )
    return analyze_schedule(sched)


def test_exec_summary_uses_ollama_when_reachable() -> None:
    with patch(_URLOPEN, return_value=_fake_urlopen(_chat_body("AI-polished executive summary."))):
        out = generate_executive_summary(_tiny_analysis(), backend=OllamaBackend(model="llama3.2"))
    assert out == "AI-polished executive summary."


def test_exec_summary_falls_back_to_deterministic_when_ollama_down() -> None:
    with patch(_URLOPEN, side_effect=urllib.error.URLError("refused")):
        out = generate_executive_summary(_tiny_analysis(), backend=OllamaBackend())
    # The deterministic factual narrative is returned unchanged (never errors out).
    assert "SCHEDULE FORENSICS — EXECUTIVE SUMMARY" in out
