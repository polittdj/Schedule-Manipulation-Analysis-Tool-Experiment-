"""M1 smoke tests: the app boots, /health responds, and the 500 MB upload ceiling and
its 413 handler behave."""

from __future__ import annotations

from flask import request

from app import create_app
from app.config import MAX_UPLOAD_BYTES


def test_app_boots_and_health_ok() -> None:
    app = create_app({"TESTING": True})
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_max_content_length_is_500mb() -> None:
    app = create_app()
    assert app.config["MAX_CONTENT_LENGTH"] == MAX_UPLOAD_BYTES == 500 * 1024 * 1024


def test_oversized_request_returns_413_json() -> None:
    # Shrink the ceiling so we can trip it without moving 500 MB of bytes.
    app = create_app({"MAX_CONTENT_LENGTH": 16})

    @app.post("/echo")
    def echo() -> str:
        request.get_data()  # forces the body read that enforces the limit
        return "ok"

    client = app.test_client()
    resp = client.post("/echo", data=b"x" * 256)
    assert resp.status_code == 413
    body = resp.get_json()
    assert body["error"] == "request_entity_too_large"
    assert body["max_content_length_bytes"] == 16
