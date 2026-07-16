"""Auth unit tests, including the non-ASCII regression.

secrets.compare_digest raises TypeError on non-ASCII str — comparing as UTF-8
bytes (auth.py) is what keeps a non-ASCII password from 500-ing every request.
"""
import base64

import pytest

from app.auth import is_authorized
from app.config import get_settings


def _basic(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


@pytest.fixture
def creds(monkeypatch):
    """Enable auth on the cached settings singleton for one test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_username", "admin")
    monkeypatch.setattr(settings, "auth_password", "pässwörd-日本語")
    return settings


def test_disabled_auth_allows_everything():
    assert is_authorized(None)
    assert is_authorized("Basic garbage")


def test_correct_non_ascii_password_accepted(creds):
    assert is_authorized(_basic("admin", "pässwörd-日本語"))


def test_wrong_password_rejected_not_crashed(creds):
    # Attacker-controlled non-ASCII input must return False, not raise.
    assert not is_authorized(_basic("admin", "wröng-ünïcode"))
    assert not is_authorized(_basic("ädmin", "pässwörd-日本語"))


def test_malformed_headers_rejected(creds):
    assert not is_authorized(None)
    assert not is_authorized("Bearer abc")
    assert not is_authorized("Basic not-base64!!!")
    assert not is_authorized(_basic("admin", "").rstrip("="))  # truncated token
    # base64 of a string with no colon separator
    no_colon = base64.b64encode(b"admin-no-separator").decode("ascii")
    assert not is_authorized(f"Basic {no_colon}")
