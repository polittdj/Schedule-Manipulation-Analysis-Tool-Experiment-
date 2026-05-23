"""Inference-routing tests -- LAW 1 fail-closed gate + NullInferenceBackend."""

from __future__ import annotations

import pytest

from schedule_forensics.inference import (
    DEFAULT_CLASSIFICATION,
    Classification,
    ClassificationError,
    InferenceError,
    NullInferenceBackend,
    OllamaBackend,
    UnclassifiedClaudeBackend,
    select_backend,
)


def test_default_classification_is_cui() -> None:
    assert DEFAULT_CLASSIFICATION is Classification.CUI


def test_null_backend_is_local_and_deterministic() -> None:
    backend = NullInferenceBackend()
    assert backend.is_local is True
    assert backend.summarize("hello world") == "hello world"
    assert backend.summarize("x") == backend.summarize("x")


def test_cui_allows_local_backends() -> None:
    assert select_backend(Classification.CUI, NullInferenceBackend()).name == "null"
    assert select_backend(Classification.CUI, OllamaBackend()).name == "ollama"


def test_cui_forbids_network_backend() -> None:
    # The core LAW 1 gate: a non-local backend cannot be selected under CUI.
    with pytest.raises(ClassificationError, match="LAW 1"):
        select_backend(Classification.CUI, UnclassifiedClaudeBackend())


def test_unclassified_allows_network_backend() -> None:
    backend = select_backend(Classification.UNCLASSIFIED, UnclassifiedClaudeBackend())
    assert backend.is_local is False


def test_ollama_summarize_not_wired_raises() -> None:
    with pytest.raises(InferenceError, match="not wired"):
        OllamaBackend().summarize("narrative")


def test_claude_summarize_not_wired_raises() -> None:
    with pytest.raises(InferenceError):
        UnclassifiedClaudeBackend().summarize("narrative")
