"""Flask configuration."""

from __future__ import annotations

# 500 MB upload ceiling. Schedule exports are large; this bounds the request body
# Werkzeug accepts before raising RequestEntityTooLarge (HTTP 413).
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


class Config:
    """Base application configuration."""

    MAX_CONTENT_LENGTH: int = MAX_UPLOAD_BYTES
    TESTING: bool = False
