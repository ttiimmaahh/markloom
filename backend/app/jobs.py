"""Job model + status state machine — the contract between API, worker, cleanup.

Lifecycle of one conversion:

    upload -> [QUEUED] --worker claims--> [PROCESSING] --+--> [DONE]    (md written)
                                                         |
                                                         +--> [FAILED]  (error saved)

Every component talks through the `status` column rather than to each other:
  - the API inserts QUEUED rows and reads status for polling,
  - the worker claims QUEUED -> PROCESSING and finishes DONE/FAILED,
  - the cleanup scheduler deletes old rows.

Almost everything below is mechanical and provided. The TWO functions at the
bottom — can_transition() and recover_interrupted_jobs() — encode *decisions*,
not mechanics, so they are left for you to implement. The rest of the module
already calls them, so the app is wired to your policy the moment you fill them.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from .config import get_settings
from .db import get_connection
from .storage import upload_path


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ConversionMode(StrEnum):
    STANDARD = "standard"  # fast, deterministic text extraction
    ENHANCED = "enhanced"  # + LLM OCR of embedded images (slower, needs an LLM)


class InvalidTransition(Exception):
    """Raised when set_status() is asked to make a move can_transition() forbids."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    orig_filename: str
    file_type: str
    size_bytes: int
    status: JobStatus
    mode: ConversionMode
    attempts: int
    error: str | None
    md_path: str | None
    created_at: str
    completed_at: str | None

    @classmethod
    def from_row(cls, row) -> "Job":
        return cls(
            id=row["id"],
            orig_filename=row["orig_filename"],
            file_type=row["file_type"],
            size_bytes=row["size_bytes"],
            status=JobStatus(row["status"]),
            mode=ConversionMode(row["mode"]),
            attempts=row["attempts"],
            error=row["error"],
            md_path=row["md_path"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )


# ---------------------------------------------------------------------------
# CRUD + queue operations (mechanical — provided)
# ---------------------------------------------------------------------------

def create_job(
    orig_filename: str,
    file_type: str,
    size_bytes: int,
    mode: ConversionMode = ConversionMode.STANDARD,
) -> Job:
    """Insert a new QUEUED job. The API calls this right after saving an upload."""
    job = Job(
        id=str(uuid.uuid4()),
        orig_filename=orig_filename,
        file_type=file_type,
        size_bytes=size_bytes,
        status=JobStatus.QUEUED,
        mode=mode,
        attempts=0,
        error=None,
        md_path=None,
        created_at=_utcnow_iso(),
        completed_at=None,
    )
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO jobs "
            "(id, orig_filename, file_type, size_bytes, status, mode, attempts, error, md_path, created_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.id, job.orig_filename, job.file_type, job.size_bytes,
             job.status, job.mode, job.attempts, job.error, job.md_path, job.created_at, job.completed_at),
        )
    return job


def get_job(job_id: str) -> Job | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def list_jobs(limit: int = 100) -> list[Job]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [Job.from_row(r) for r in rows]


def set_status(
    job_id: str,
    target: JobStatus,
    *,
    error: str | None = None,
    md_path: str | None = None,
) -> Job:
    """Transition a job to `target`, enforcing the state machine you define.

    Raises InvalidTransition if can_transition() rejects the move, or KeyError
    if the job is gone. `completed_at` is stamped automatically on terminal
    states. This is the ONLY sanctioned way to change a job's status (except the
    atomic claim below), so your policy is enforced everywhere.
    """
    job = get_job(job_id)
    if job is None:
        raise KeyError(f"job {job_id} not found")
    if not can_transition(job.status, target):
        raise InvalidTransition(f"illegal transition {job.status} -> {target}")

    completed_at = (
        _utcnow_iso()
        if target in (JobStatus.DONE, JobStatus.FAILED)
        else job.completed_at
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, error = ?, md_path = ?, completed_at = ? WHERE id = ?",
            (
                target,
                error if error is not None else job.error,
                md_path if md_path is not None else job.md_path,
                completed_at,
                job_id,
            ),
        )
    return get_job(job_id)  # re-read to return the updated row


def claim_next_queued() -> Job | None:
    """Atomically move the oldest QUEUED job to PROCESSING and return it.

    The UPDATE is guarded by `status = QUEUED`, so if two worker threads race,
    the second one's UPDATE matches zero rows and returns None. This atomicity is
    why claiming bypasses set_status()/can_transition(): QUEUED -> PROCESSING is
    always legal, and doing it in one statement is what prevents double-claims.

    Also increments `attempts` — the counter the crash-recovery poison-pill guard
    reads. (Requires SQLite >= 3.35 for RETURNING, which ships with Python 3.11+.)
    """
    with get_connection() as conn:
        row = conn.execute(
            "UPDATE jobs SET status = ?, attempts = attempts + 1 "
            "WHERE id = (SELECT id FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1) "
            "RETURNING *",
            (JobStatus.PROCESSING, JobStatus.QUEUED),
        ).fetchone()
    return Job.from_row(row) if row else None


def delete_job(job_id: str) -> Job | None:
    """Delete a job row and return it (so the caller can unlink its files).

    Returns None if the job doesn't exist.
    """
    job = get_job(job_id)
    if job is None:
        return None
    with get_connection() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return job


def purge_expired(retention_days: int) -> list[Job]:
    """Delete job rows older than `retention_days` and return them.

    The caller (cleanup.py) unlinks each returned job's md file. A value <= 0
    disables expiry entirely (keep forever).
    """
    if retention_days <= 0:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM jobs WHERE created_at < ?", (cutoff,)).fetchall()
        conn.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
    return [Job.from_row(r) for r in rows]


# ===========================================================================
# Transition policy
# ===========================================================================
#
# DONE and FAILED are TERMINAL. This is a direct consequence of markdown-only
# retention: the worker deletes the original upload as soon as processing ends,
# so a finished job (done or failed) has nothing left to re-convert. There is no
# "retry a failed job" because the input is gone — the user re-uploads instead,
# which creates a fresh job.
#
# PROCESSING -> QUEUED exists solely for crash recovery: a job interrupted
# mid-convert still has its original on disk (the worker only deletes it after
# finishing), so it is safe to re-queue. See recover_interrupted_jobs().
_ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.PROCESSING},
    JobStatus.PROCESSING: {JobStatus.DONE, JobStatus.FAILED, JobStatus.QUEUED},
    JobStatus.DONE: set(),
    JobStatus.FAILED: set(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """Return True if a job may move from `current` to `target`.

    Enforced by set_status() everywhere. No-op moves (X -> X) are rejected, so a
    double-completion attempt surfaces as an InvalidTransition rather than
    silently overwriting a terminal state.
    """
    return target in _ALLOWED_TRANSITIONS.get(current, set())


# ===========================================================================
# Crash recovery (hybrid: retry until attempts exhausted, then fail)
# ===========================================================================
def recover_interrupted_jobs() -> int:
    """Reconcile jobs left in PROCESSING when the container died mid-convert.

    Any job still marked PROCESSING on startup was interrupted — its worker
    thread died with the process. Its original upload is still on disk (the
    worker deletes originals only after finishing), so we can safely re-run it.

    Poison-pill guard: a file that crashes the worker would otherwise re-crash it
    on every boot. So we retry only while the job has attempts left
    (settings.max_attempts); once exhausted we fail it with an explanatory error
    rather than loop forever. `attempts` is incremented in claim_next_queued().

    Called once from main.py's startup, after init_db(). Returns the count
    reconciled (for a startup log line).
    """
    settings = get_settings()
    reconciled = 0
    for job in list_jobs(limit=1_000_000):
        if job.status != JobStatus.PROCESSING:
            continue
        if job.attempts >= settings.max_attempts:
            set_status(
                job.id,
                JobStatus.FAILED,
                error=f"Interrupted by restart; gave up after {job.attempts} attempt(s).",
            )
            # Giving up means no worker will ever process (and thus delete) the
            # original upload — remove it now or it lingers on disk forever.
            upload_path(job.id, job.file_type).unlink(missing_ok=True)
        else:
            set_status(job.id, JobStatus.QUEUED)
        reconciled += 1
    return reconciled
