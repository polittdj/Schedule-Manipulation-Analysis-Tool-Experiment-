"""HTTP routes.

A thin transport layer. The analysis core lives in ``app.models`` / ``app.cpm`` /
``app.metrics`` and stays free of Flask.
"""

from __future__ import annotations

from flask import Flask, Response, jsonify


def register_routes(app: Flask) -> None:
    """Register HTTP routes on the given app."""

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok"})
