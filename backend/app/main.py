"""FastAPI application: API routes, optional auth, background wiring, static SPA.

Request lifecycle for a conversion:
    POST /api/convert   -> validate, save upload, create QUEUED job, notify worker, 202
    GET  /api/jobs/{id} -> poll status until done/failed
    GET  /api/download/{id} -> stream the .md once done
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import cleanup
from .auth import is_authorized
from .config import get_settings
from .db import init_db
from .jobs import (
    ConversionMode,
    Job,
    JobStatus,
    create_job,
    delete_job,
    get_job,
    list_jobs,
    recover_interrupted_jobs,
)
from .storage import upload_path
from .worker import worker

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("markloom")

# In the container, backend/ is copied to /app and the built frontend to /app/static.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    init_db()
    recovered = recover_interrupted_jobs()
    log.info("startup: reconciled %s interrupted job(s)", recovered)
    worker.start()
    cleanup.start()
    yield
    # --- shutdown ---
    worker.stop()
    cleanup.stop()


app = FastAPI(title="Markloom", lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Enforce optional Basic auth over everything except the health probe."""
    settings = get_settings()
    if settings.auth_enabled and request.url.path != "/api/health":
        if not is_authorized(request.headers.get("Authorization")):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="markloom"'},
            )
    return await call_next(request)


def _job_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "orig_filename": job.orig_filename,
        "file_type": job.file_type,
        "size_bytes": job.size_bytes,
        "status": job.status,
        "error": job.error,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "mode": job.mode,
        "download_url": f"/api/download/{job.id}" if job.status == JobStatus.DONE else None,
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/capabilities")
def capabilities() -> dict:
    """What optional features are configured — the SPA uses this to show/hide UI."""
    return {"llm_available": get_settings().llm_enabled}


@app.post("/api/convert", status_code=202)
async def convert_endpoint(
    file: UploadFile = File(...),
    enhanced: bool = Form(False),
) -> dict:
    settings = get_settings()
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in settings.allowed_ext_set:
        raise HTTPException(415, f"Unsupported file type: .{ext or '(none)'}")

    if enhanced and not settings.llm_enabled:
        raise HTTPException(400, "Enhanced conversion requires an LLM to be configured.")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "Empty file.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB limit.")

    mode = ConversionMode.ENHANCED if enhanced else ConversionMode.STANDARD
    job = create_job(orig_filename=filename, file_type=ext, size_bytes=len(data), mode=mode)
    upload_path(job.id, ext).write_bytes(data)
    worker.notify()
    return _job_dict(job)


@app.get("/api/jobs")
def jobs_endpoint() -> list[dict]:
    return [_job_dict(j) for j in list_jobs()]


@app.get("/api/jobs/{job_id}")
def job_endpoint(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return _job_dict(job)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job_endpoint(job_id: str) -> Response:
    job = delete_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    # Remove the converted markdown and any lingering original upload.
    if job.md_path:
        Path(job.md_path).unlink(missing_ok=True)
    upload_path(job.id, job.file_type).unlink(missing_ok=True)
    return Response(status_code=204)


@app.get("/api/download/{job_id}")
def download_endpoint(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if job.status != JobStatus.DONE or not job.md_path:
        raise HTTPException(409, "Conversion is not complete.")
    path = Path(job.md_path)
    if not path.exists():
        raise HTTPException(410, "Converted file is no longer available.")
    download_name = f"{Path(job.orig_filename).stem}.md"
    return FileResponse(path, media_type="text/markdown", filename=download_name)


# Serve the built React SPA for everything not matched above. Guarded so the app
# still boots in dev before the frontend has been built.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    log.warning("static dir %s not found; SPA not served (dev without build?)", STATIC_DIR)
