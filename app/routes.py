"""HTTP routes.

A thin transport layer over the analysis core (``app.analysis`` / ``app.cpm`` /
``app.metrics``), which stays free of Flask.
"""

from __future__ import annotations

from flask import Flask, Response, jsonify, request
from pydantic import ValidationError

from app.analysis import analyze_schedule
from app.exceptions import CPMError
from app.models import Schedule


def register_routes(app: Flask) -> None:
    """Register HTTP routes on the given app."""

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok"})

    @app.post("/analyze")
    def analyze() -> Response | tuple[Response, int]:
        """Validate a JSON Schedule body, run CPM + DCMA metrics, return a JSON report."""
        try:
            schedule = Schedule.model_validate_json(request.get_data())
        except ValidationError as exc:
            return jsonify({"error": "invalid_schedule", "message": str(exc)}), 400
        try:
            report = analyze_schedule(schedule)
        except CPMError as exc:
            return jsonify({"error": "cpm_error", "message": str(exc)}), 422
        return jsonify(report.to_dict())
