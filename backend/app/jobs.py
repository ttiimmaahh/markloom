"""Job model + status state machine — the contract between API, worker, cleanup.

Lifecycle of one conversion:

    upload -> [QUEUED] --worker claims--> [PROCESSING] -> [DONE] or [FAILED]
                    |                         |
                    +-------------------------+---------> [CANCELED]

Every component talks through the `status` column rather than to each other:
  - the API inserts QUEUED rows and reads status for polling,
  - the worker claims QUEUED -> PROCESSING and finishes DONE/FAILED,
  - the cleanup scheduler deletes old rows.

Most of the module is mechanical CRUD. The policy lives in two places:
can_transition() (which moves the state machine allows — DONE/FAILED are
terminal) and recover_interrupted_jobs() (what happens to jobs stranded in
PROCESSING by a crash: re-queue until attempts run out, then fail).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from .config import AUDIO_EXTENSIONS, get_settings
from .db import get_connection
from .storage import markdown_path, upload_path


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


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
            (
                job.id,
                job.orig_filename,
                job.file_type,
                job.size_bytes,
                job.status,
                job.mode,
                job.attempts,
                job.error,
                job.md_path,
                job.created_at,
                job.completed_at,
            ),
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

    terminal = target in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED)
    completed_at = _utcnow_iso() if terminal else job.completed_at
    next_error = (
        None
        if target == JobStatus.CANCELED
        else (error if error is not None else job.error)
    )
    next_md_path = (
        None
        if target == JobStatus.CANCELED
        else (md_path if md_path is not None else job.md_path)
    )

    # Compare-and-set is the linearization point for cancel vs. completion.
    # Whichever transition updates the observed source status first wins; a late
    # worker can never overwrite CANCELED with DONE/FAILED (or vice versa).
    with get_connection() as conn:
        row = conn.execute(
            "UPDATE jobs SET status = ?, error = ?, md_path = ?, completed_at = ? "
            "WHERE id = ? AND status = ? RETURNING *",
            (target, next_error, next_md_path, completed_at, job_id, job.status),
        ).fetchone()
    if row is not None:
        return Job.from_row(row)

    latest = get_job(job_id)
    if latest is None:
        raise KeyError(f"job {job_id} not found")
    raise InvalidTransition(
        f"job changed from {job.status} to {latest.status} before transition to {target}"
    )


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


def can_cancel(job: Job) -> bool:
    """Whether the job can be stopped without leaving in-process work running."""
    if job.status == JobStatus.QUEUED:
        return True
    return (
        job.status == JobStatus.PROCESSING
        and job.mode == ConversionMode.ENHANCED
        and job.file_type not in AUDIO_EXTENSIONS
    )


def cancel_job(job_id: str) -> Job:
    """Atomically cancel queued or killable Enhanced work.

    Eligibility and transition use the same status/mode/type snapshot. If a
    queued job is claimed between the read and update, eligibility is rechecked:
    Enhanced documents remain cancelable, while Standard/audio work is rejected
    once its in-process conversion has started.
    """
    while True:
        job = get_job(job_id)
        if job is None:
            raise KeyError(f"job {job_id} not found")
        if job.status == JobStatus.CANCELED:
            return job
        if not can_cancel(job):
            raise InvalidTransition(
                f"job {job_id} cannot be canceled from {job.status}"
            )

        with get_connection() as conn:
            row = conn.execute(
                "UPDATE jobs SET status = ?, error = NULL, md_path = NULL, "
                "completed_at = ? WHERE id = ? AND status = ? AND mode = ? "
                "AND file_type = ? RETURNING *",
                (
                    JobStatus.CANCELED,
                    _utcnow_iso(),
                    job_id,
                    job.status,
                    job.mode,
                    job.file_type,
                ),
            ).fetchone()
        if row is not None:
            return Job.from_row(row)
        # A concurrent claim/completion/delete won. Re-read to decide whether
        # the new state is still safely cancelable, terminal, or gone.


def delete_job(job_id: str) -> Job | None:
    """Atomically delete and return a job row so its files can be unlinked."""
    with get_connection() as conn:
        row = conn.execute(
            "DELETE FROM jobs WHERE id = ? RETURNING *", (job_id,)
        ).fetchone()
    return Job.from_row(row) if row else None


def purge_expired(retention_days: int) -> list[Job]:
    """Delete job rows older than `retention_days` and return them.

    The caller (cleanup.py) unlinks each returned job's md file. A value <= 0
    disables expiry entirely (keep forever).
    """
    if retention_days <= 0:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    terminal = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED)
    with get_connection() as conn:
        rows = conn.execute(
            "DELETE FROM jobs WHERE created_at < ? AND status IN (?, ?, ?) RETURNING *",
            (cutoff, *terminal),
        ).fetchall()
    return [Job.from_row(r) for r in rows]


# ===========================================================================
# Transition policy
# ===========================================================================
#
# DONE, FAILED, and CANCELED are TERMINAL. This follows from markdown-only
# retention: the worker deletes the original upload as soon as processing ends
# or cancellation wins, so a terminal job has nothing left to re-convert. There is no
# "retry a failed job" because the input is gone — the user re-uploads instead,
# which creates a fresh job.
#
# PROCESSING -> QUEUED exists solely for crash recovery: a job interrupted
# mid-convert still has its original on disk (the worker only deletes it after
# finishing), so it is safe to re-queue. See recover_interrupted_jobs().
_ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.PROCESSING, JobStatus.CANCELED},
    JobStatus.PROCESSING: {
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.CANCELED,
        JobStatus.QUEUED,
    },
    JobStatus.DONE: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELED: set(),
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
def _remove_interrupted_outputs(job_id: str) -> None:
    """Best-effort cleanup for output files left by a hard process exit."""
    output = markdown_path(job_id)
    paths = [
        output,
        *output.parent.glob(f".{job_id}.*.md.tmp"),
        *output.parent.glob(f".{job_id}.*.result.json"),
    ]
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Recovery must still reconcile the durable row; retention or an
            # operator can remove an artifact with unusual permissions later.
            pass


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
        _remove_interrupted_outputs(job.id)
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
