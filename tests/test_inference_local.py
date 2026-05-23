"""Tests for the LocalOpenAIBackend + backend_from_env (LAW 1 loopback-only).

The HTTP call is mocked, so these run with no model server. The key LAW-1 test is
that a non-loopback base URL is refused at construction (fail closed).
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from schedule_forensics.inference import (
    Classification,
    ClassificationError,
    InferenceError,
    LocalOpenAIBackend,
    NullInferenceBackend,
    backend_from_env,
    select_backend,
)

_URLOPEN = "schedule_forensics.inference.urllib.request.urlopen"


def _fake_urlopen(body: bytes) -> MagicMock:
    """A context-manager mock whose ``.read()`` returns ``body`` (mimics urlopen)."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    return cm


def _chat_body(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


# --- LAW 1: loopback enforcement (fail closed) ---
def test_rejects_non_loopback_base_url() -> None:
    with pytest.raises(ClassificationError, match="loopback"):
        LocalOpenAIBackend(base_url="http://evil.example.com/v1")


def test_accepts_loopback_hosts() -> None:
    assert LocalOpenAIBackend(base_url="http://127.0.0.1:8080/v1").is_local is True
    assert LocalOpenAIBackend(base_url="http://localhost:1234/v1").is_local is True


def test_cui_allows_local_openai_backend() -> None:
    # is_local=True so the CUI router permits it (it cannot reach off-machine).
    backend = LocalOpenAIBackend(base_url="http://127.0.0.1:11434/v1")
    assert select_backend(Classification.CUI, backend).name == "local-openai"


# --- summarize() behaviour (HTTP mocked) ---
def test_summarize_returns_model_content() -> None:
    backend = LocalOpenAIBackend(base_url="http://127.0.0.1:8080/v1", model="qwen")
    with patch(_URLOPEN, return_value=_fake_urlopen(_chat_body("Polished narrative."))):
        assert backend.summarize("factual narrative") == "Polished narrative."


def test_summarize_sends_model_and_narrative() -> None:
    backend = LocalOpenAIBackend(base_url="http://127.0.0.1:8080/v1", model="qwen-32b")
    captured: dict[str, Any] = {}

    def _capture(request: Any, *args: Any, **kwargs: Any) -> MagicMock:
        captured["payload"] = json.loads(request.data)
        return _fake_urlopen(_chat_body("ok"))

    with patch(_URLOPEN, side_effect=_capture):
        backend.summarize("THE NARRATIVE TEXT")
    assert captured["payload"]["model"] == "qwen-32b"
    # the narrative is sent verbatim as the user message (model only rephrases it)
    assert any("THE NARRATIVE TEXT" in m["content"] for m in captured["payload"]["messages"])


def test_summarize_unreachable_raises_clear_error() -> None:
    backend = LocalOpenAIBackend(base_url="http://127.0.0.1:8080/v1")
    with (
        patch(_URLOPEN, side_effect=urllib.error.URLError("connection refused")),
        pytest.raises(InferenceError, match="not reachable"),
    ):
        backend.summarize("x")


def test_summarize_malformed_response_raises() -> None:
    backend = LocalOpenAIBackend(base_url="http://127.0.0.1:8080/v1")
    with (
        patch(_URLOPEN, return_value=_fake_urlopen(b'{"no":"choices here"}')),
        pytest.raises(InferenceError, match="unexpected response"),
    ):
        backend.summarize("x")


def test_summarize_empty_completion_raises() -> None:
    backend = LocalOpenAIBackend(base_url="http://127.0.0.1:8080/v1")
    with (
        patch(_URLOPEN, return_value=_fake_urlopen(_chat_body("   "))),
        pytest.raises(InferenceError, match="empty"),
    ):
        backend.summarize("x")


# --- backend_from_env factory ---
def test_env_without_url_returns_null() -> None:
    assert isinstance(backend_from_env({}), NullInferenceBackend)


def test_env_with_url_returns_local_backend() -> None:
    backend = backend_from_env(
        {"SF_LLM_BASE_URL": "http://127.0.0.1:8080/v1", "SF_LLM_MODEL": "qwen2.5:32b"}
    )
    assert isinstance(backend, LocalOpenAIBackend)
    assert backend.model == "qwen2.5:32b"
    assert backend.base_url == "http://127.0.0.1:8080/v1"


def test_env_with_non_loopback_url_fails_closed() -> None:
    with pytest.raises(ClassificationError):
        backend_from_env({"SF_LLM_BASE_URL": "http://10.0.0.5:8080/v1"})
