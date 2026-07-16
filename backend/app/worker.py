"""Background worker: pulls QUEUED jobs and runs MarkItDown off the event loop.

MarkItDown is synchronous and CPU-bound, so it must NOT run on FastAPI's async
loop (one big PDF would freeze every request). A small pool of daemon threads
claims jobs atomically and converts them. The API calls `worker.notify()` after
enqueuing so a thread wakes immediately; a 5s poll fallback guarantees progress
even if a wake is missed.

Per-job flow (markdown-only retention):
    claim QUEUED -> PROCESSING (atomic, increments attempts)
    convert -> write <id>.md -> set DONE
       or on error -> set FAILED
    finally -> delete the original upload
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config import get_settings
from .converter import ConversionError, convert
from .jobs import ConversionMode, InvalidTransition, JobStatus, Job, claim_next_queued, set_status
from .storage import markdown_path, upload_path

log = logging.getLogger("markloom.worker")


class Worker:
    def __init__(self) -> None:
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._wake = threading.Event()

    def start(self) -> None:
        n = max(1, get_settings().worker_threads)
        for i in range(n):
            t = threading.Thread(target=self._loop, name=f"worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        log.info("worker started with %d thread(s)", n)

    def notify(self) -> None:
        """Wake an idle worker — called by the API after a new job is enqueued."""
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = claim_next_queued()
            if job is None:
                # Nothing queued; wait for a nudge or poll again in 5s.
                self._wake.wait(timeout=5.0)
                self._wake.clear()
                continue
            self._process(job)

    def _finish(self, job_id: str, status: JobStatus, **kw) -> None:
        """Set a terminal status, tolerating a job that was deleted mid-convert.

        If the row is gone (or the transition is rejected), the markdown we just
        wrote is unreachable — no DB row will ever point at it — so unlink it
        rather than leak it on disk forever.
        """
        try:
            set_status(job_id, status, **kw)
        except KeyError:
            log.info("job %s vanished (deleted?) before %s; skipping", job_id, status)
            self._discard_output(kw.get("md_path"))
        except InvalidTransition as e:
            log.warning("job %s: %s", job_id, e)
            self._discard_output(kw.get("md_path"))

    @staticmethod
    def _discard_output(md_path: str | None) -> None:
        if md_path:
            try:
                Path(md_path).unlink(missing_ok=True)
            except OSError:
                log.warning("could not delete orphaned markdown %s", md_path)

    def _process(self, job: Job) -> None:
        src = upload_path(job.id, job.file_type)
        enhanced = job.mode == ConversionMode.ENHANCED
        try:
            text = convert(src, enhanced=enhanced)
            out = markdown_path(job.id)
            out.write_text(text, encoding="utf-8")
            self._finish(job.id, JobStatus.DONE, md_path=str(out))
            log.info("converted job %s (%s)", job.id, job.orig_filename)
        except ConversionError as e:
            self._finish(job.id, JobStatus.FAILED, error=str(e))
            log.warning("job %s failed: %s", job.id, e)
        except Exception as e:  # noqa: BLE001 - never let a bad file kill the thread
            self._finish(job.id, JobStatus.FAILED, error=f"Unexpected error: {e}")
            log.exception("job %s crashed unexpectedly", job.id)
        finally:
            # Markdown-only retention: drop the original once we're done with it.
            try:
                src.unlink(missing_ok=True)
            except OSError:
                log.warning("could not delete original upload for job %s", job.id)


# Module-level singleton the API and lifespan import.
worker = Worker()
