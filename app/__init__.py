"""Application factory for the Schedule Manipulation Analysis Tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import Flask

from app.config import Config
from app.errors import register_error_handlers
from app.routes import register_routes


def create_app(overrides: Mapping[str, Any] | None = None) -> Flask:
    """Build and configure a Flask application instance.

    Args:
        overrides: Optional config values layered on top of ``Config`` — convenient in
            tests (e.g. ``{"TESTING": True}``) and for shrinking the upload ceiling.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(dict(overrides))

    register_error_handlers(app)
    register_routes(app)
    return app


__all__ = ["create_app"]
