"""FastAPI application: API routes, optional auth, background wiring, static SPA.

Request lifecycle for a conversion:
    POST /api/convert   -> validate, save upload, create QUEUED job, notify worker, 202
    GET  /api/jobs/{id} -> poll status until done/failed
    GET  /api/download/{id} -> stream the .md once done
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse, JSONResponse, Response  # pyright: ignore[reportMissingImports]
from fastapi.staticfiles import StaticFiles  # pyright: ignore[reportMissingImports]

from . import cleanup
from .auth import is_authorized
from .config import AUDIO_EXTENSIONS, get_settings
from .db import init_db
from .jobs import (
    ConversionMode,
    InvalidTransition,
    Job,
    JobStatus,
    can_cancel,
    cancel_job,
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


app = FastAPI(title="Markloom", version=get_settings().app_version, lifespan=lifespan)


# Slack on top of MAX_UPLOAD_MB for multipart framing (boundaries, part headers,
# the `enhanced` field) so a file exactly at the limit isn't rejected.
_MULTIPART_OVERHEAD = 64 * 1024


# NOTE: Starlette runs middleware in reverse registration order, so this one
# (registered first) runs INSIDE auth_middleware — auth is checked before size.
@app.middleware("http")
async def upload_size_guard(request: Request, call_next):
    """Reject oversized uploads from the Content-Length header, BEFORE the
    multipart body is parsed — otherwise the whole body gets read/spooled first
    and a huge upload can exhaust memory or disk regardless of MAX_UPLOAD_MB.
    Bodies without a Content-Length are capped during the chunked copy in
    convert_endpoint instead.
    """
    if request.method == "POST" and request.url.path == "/api/convert":
        declared = request.headers.get("content-length", "")
        limit = get_settings().max_upload_bytes + _MULTIPART_OVERHEAD
        try:
            declared_size = int(declared)
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > limit:
            return JSONResponse(
                {
                    "detail": f"File exceeds the {get_settings().max_upload_mb} MB limit."
                },
                status_code=413,
            )
    return await call_next(request)


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
        "can_cancel": can_cancel(job),
        "download_url": f"/api/download/{job.id}"
        if job.status == JobStatus.DONE
        else None,
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/capabilities")
def capabilities() -> dict:
    """Server metadata the SPA reads on load: optional-feature flags + version."""
    settings = get_settings()
    return {"llm_available": settings.llm_enabled, "version": settings.app_version}


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

    enhanced_document = enhanced and ext not in AUDIO_EXTENSIONS
    if enhanced_document and not settings.llm_enabled:
        raise HTTPException(
            400, "Enhanced conversion requires an LLM to be configured."
        )

    # Copy to disk in chunks, enforcing the size cap as bytes arrive — never the
    # whole file in memory (the Content-Length middleware can't catch chunked
    # bodies or a lying header, so the cap is re-checked here).
    # The upload is staged under a temp name and only renamed to the path the
    # worker looks for AFTER the job row exists: inserting the QUEUED row first
    # would let a worker claim the job before its file is on disk and fail it.
    tmp = settings.upload_dir / f"{uuid.uuid4().hex}.tmp"
    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        413, f"File exceeds the {settings.max_upload_mb} MB limit."
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "Empty file.")

        mode = ConversionMode.ENHANCED if enhanced_document else ConversionMode.STANDARD
        job = create_job(
            orig_filename=filename, file_type=ext, size_bytes=size, mode=mode
        )
        tmp.rename(upload_path(job.id, ext))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
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


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str) -> dict:
    try:
        job = cancel_job(job_id)
    except KeyError as e:
        raise HTTPException(404, "Job not found.") from e
    except InvalidTransition as e:
        raise HTTPException(409, "This conversion can no longer be stopped.") from e

    # The DB transition wins first so a late completion cannot overwrite it.
    # The worker also polls persisted status, covering cancel-before-register;
    # this in-process signal makes the common path immediate.
    worker.cancel(job.id)
    upload_path(job.id, job.file_type).unlink(missing_ok=True)
    return _job_dict(job)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job_endpoint(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")

    # Deletion is retention, not a hidden cancellation mechanism. Stop active
    # work first; if it became non-killable Standard/audio work, keep the row and
    # tell the caller rather than pretending deletion stopped it.
    if job.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
        try:
            job = cancel_job(job_id)
        except InvalidTransition as e:
            latest = get_job(job_id)
            if latest is None:
                raise HTTPException(404, "Job not found.") from e
            if latest.status not in (
                JobStatus.DONE,
                JobStatus.FAILED,
                JobStatus.CANCELED,
            ):
                raise HTTPException(
                    409,
                    "Stop this conversion before deleting it.",
                ) from e
            job = latest
        worker.cancel(job_id)

    deleted = delete_job(job_id)
    if deleted is None:
        raise HTTPException(404, "Job not found.")
    if deleted.md_path:
        Path(deleted.md_path).unlink(missing_ok=True)
    upload_path(deleted.id, deleted.file_type).unlink(missing_ok=True)


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
    log.warning(
        "static dir %s not found; SPA not served (dev without build?)", STATIC_DIR
    )
