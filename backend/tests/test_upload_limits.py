"""Upload size-limit regression tests.

The limit must be enforced BEFORE the body is materialised in memory: once via
the Content-Length middleware, and again as a running cap during the chunked
copy (for chunked bodies or a lying header). These tests exercise the
user-visible contract: an over-limit upload gets a 413 and leaves nothing
behind on disk or in the job history.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def one_mb_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)


def test_oversized_upload_rejected_413(client, one_mb_limit):
    big = b"x" * (2 * 1024 * 1024)
    r = client.post("/api/convert", files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413
    assert "1 MB" in r.json()["detail"]


def test_oversized_upload_leaves_no_job_or_file(client, one_mb_limit):
    before = {j["id"] for j in client.get("/api/jobs").json()}
    client.post("/api/convert", files={"file": ("big.txt", b"x" * (2 * 1024 * 1024), "text/plain")})
    after = {j["id"] for j in client.get("/api/jobs").json()}
    assert before == after
    upload_dir = get_settings().upload_dir
    assert not list(upload_dir.glob("*.tmp")), "staged temp file was not cleaned up"


def test_at_limit_upload_accepted(client, one_mb_limit):
    exactly = b"x" * (1024 * 1024)
    r = client.post("/api/convert", files={"file": ("fits.txt", exactly, "text/plain")})
    assert r.status_code == 202
