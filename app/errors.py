"""Flask error handlers (the web boundary's JSON error envelope)."""

from __future__ import annotations

from flask import Flask, Response, jsonify
from werkzeug.exceptions import RequestEntityTooLarge


def register_error_handlers(app: Flask) -> None:
    """Register JSON error handlers on the given app."""

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(error: RequestEntityTooLarge) -> tuple[Response, int]:
        return (
            jsonify(
                {
                    "error": "request_entity_too_large",
                    "message": "Uploaded content exceeds the maximum allowed size.",
                    "max_content_length_bytes": app.config.get("MAX_CONTENT_LENGTH"),
                }
            ),
            413,
        )
