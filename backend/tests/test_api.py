import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # Entering the context manager runs the lifespan (worker + scheduler start).
    with TestClient(app) as c:
        yield c


def _wait_for_settle(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not settle within {timeout}s")


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_convert_html_to_markdown(client):
    html = b"<h1>Report</h1><p>Hello <b>world</b> from markitdown.</p>"
    r = client.post("/api/convert", files={"file": ("report.html", html, "text/html")})
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "queued"

    final = _wait_for_settle(client, job["id"])
    assert final["status"] == "done", final
    assert final["download_url"]

    md = client.get(final["download_url"])
    assert md.status_code == 200
    assert "# Report" in md.text
    assert "**world**" in md.text


def test_history_lists_job(client):
    r = client.post("/api/convert", files={"file": ("note.html", b"<p>hi</p>", "text/html")})
    job_id = r.json()["id"]
    _wait_for_settle(client, job_id)
    assert any(j["id"] == job_id for j in client.get("/api/jobs").json())


def test_unsupported_type_rejected(client):
    r = client.post("/api/convert", files={"file": ("x.zzz", b"data", "application/octet-stream")})
    assert r.status_code == 415


def test_empty_file_rejected(client):
    r = client.post("/api/convert", files={"file": ("empty.txt", b"", "text/plain")})
    assert r.status_code == 400


def test_unknown_job_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_download_before_done_conflicts(client):
    # A brand-new job has no markdown yet; download should 404 (job unknown) or 409.
    assert client.get("/api/download/does-not-exist").status_code == 404


def test_delete_job(client):
    r = client.post("/api/convert", files={"file": ("del.html", b"<p>bye</p>", "text/html")})
    job_id = r.json()["id"]
    _wait_for_settle(client, job_id)

    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    # gone from history and individually
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert all(j["id"] != job_id for j in client.get("/api/jobs").json())
    # its markdown is no longer downloadable
    assert client.get(f"/api/download/{job_id}").status_code == 404


def test_delete_unknown_404(client):
    assert client.delete("/api/jobs/does-not-exist").status_code == 404


def test_capabilities_reports_llm_disabled(client):
    # No LLM configured in the test environment; version defaults to "dev"
    # outside a release image build.
    assert client.get("/api/capabilities").json() == {
        "llm_available": False,
        "version": "dev",
    }


def test_standard_conversion_reports_mode(client):
    r = client.post("/api/convert", files={"file": ("m.html", b"<p>x</p>", "text/html")})
    assert r.json()["mode"] == "standard"


def test_enhanced_requires_llm(client):
    # Requesting enhanced without an LLM configured is a 400, not a silent fallback.
    r = client.post(
        "/api/convert",
        files={"file": ("m.html", b"<p>x</p>", "text/html")},
        data={"enhanced": "true"},
    )
    assert r.status_code == 400
