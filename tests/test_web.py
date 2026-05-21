"""The browser UI page loads and wires to the analyze endpoint."""

from __future__ import annotations

from app import create_app


def test_index_page_serves_ui() -> None:
    client = create_app({"TESTING": True}).test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Analyze schedule" in body  # the main button
    assert "/analyze" in body  # the page posts the schedule to the analysis endpoint
