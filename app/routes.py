"""HTTP routes.

A thin transport layer over the analysis core (``app.analysis`` / ``app.cpm`` /
``app.metrics``), which stays free of Flask.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from pydantic import ValidationError

from app.analysis import analyze_schedule
from app.exceptions import CPMError
from app.models import Schedule
from app.parsers import parse_schedule


def register_routes(app: Flask) -> None:
    """Register HTTP routes on the given app."""

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/upload")
    def upload() -> Response | tuple[Response, int]:
        """Parse an uploaded native file (.xml / .xer / .json) into the tool's Schedule JSON.

        Returns ``{"schedule": <schedule>}`` so the UI can show/edit/analyze it. ``.mpp`` is a
        binary format and is rejected with guidance to use "Save As -> XML".
        """
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "no_file", "message": "No file was uploaded."}), 400
        suffix = Path(upload.filename).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            upload.save(handle.name)
            temp_path = Path(handle.name)
        try:
            schedule = parse_schedule(temp_path)
        except NotImplementedError as exc:
            return jsonify({"error": "unsupported_format", "message": str(exc)}), 415
        except Exception as exc:
            return jsonify(
                {"error": "parse_failed", "message": f"Could not read that file: {exc}"}
            ), 400
        finally:
            temp_path.unlink(missing_ok=True)
        return jsonify({"schedule": schedule.model_dump(mode="json")})

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
