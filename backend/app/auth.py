"""Optional HTTP Basic auth (mazanoke-style, env-gated).

Active only when BOTH AUTH_USERNAME and AUTH_PASSWORD are set
(settings.auth_enabled). Otherwise the service is open — fine on a trusted LAN,
never on the public internet. Enforced as middleware in main.py so it covers
both the API and the static SPA.
"""
from __future__ import annotations

import base64
import secrets

from .config import get_settings


def is_authorized(auth_header: str | None) -> bool:
    """True if auth is disabled, or the Basic credentials match the configured pair."""
    settings = get_settings()
    if not settings.auth_enabled:
        return True
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, sep, password = decoded.partition(":")
    if not sep:
        return False
    # compare_digest on both fields to avoid leaking length/content via timing.
    # Compared as UTF-8 bytes: compare_digest raises TypeError on non-ASCII str,
    # which would 500 the request (and break non-ASCII passwords outright).
    user_ok = secrets.compare_digest(
        username.encode("utf-8"), (settings.auth_username or "").encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        password.encode("utf-8"), (settings.auth_password or "").encode("utf-8")
    )
    return user_ok and pass_ok
