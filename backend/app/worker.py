"""Background worker: claims durable jobs and converts them off the API loop.

Standard document conversion and audio transcription remain in worker threads.
Enhanced document conversion runs in a supervised child process: MarkItDown and
its provider calls are opaque synchronous work, so a process boundary is the
only reliable way to stop a stuck request without restarting Markloom.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from .config import AUDIO_EXTENSIONS, get_settings
from .converter import ConversionError, convert
from .jobs import (
    ConversionMode,
    InvalidTransition,
    Job,
    JobStatus,
    claim_next_queued,
    get_job,
    set_status,
)
from .storage import markdown_path, upload_path

log = logging.getLogger("markloom.worker")

CommandFactory = Callable[[Path, Path, Path], Sequence[str]]


class Worker:
    def __init__(
        self,
        *,
        poll_interval: float = 0.1,
        terminate_grace: float = 2.0,
        command_factory: CommandFactory | None = None,
    ) -> None:
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._active_lock = threading.Lock()
        self._active: dict[str, subprocess.Popen[bytes]] = {}
        self._poll_interval = poll_interval
        self._terminate_grace = terminate_grace
        self._command_factory = command_factory or self._enhanced_command

    @staticmethod
    def _enhanced_command(src: Path, output: Path, result: Path) -> Sequence[str]:
        return (
            sys.executable,
            "-m",
            "app.conversion_subprocess",
            str(src),
            str(output),
            str(result),
        )

    def start(self) -> None:
        self._stop.clear()
        n = max(1, get_settings().worker_threads)
        for i in range(n):
            thread = threading.Thread(
                target=self._loop,
                name=f"worker-{i}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        log.info("worker started with %d thread(s)", n)

    def notify(self) -> None:
        """Wake an idle worker after the API enqueues a job."""
        self._wake.set()

    def cancel(self, job_id: str) -> None:
        """Promptly signal this process's active Enhanced child, if registered."""
        with self._active_lock:
            process = self._active.get(job_id)
        if process is not None:
            self._signal_process(process, signal.SIGTERM)

    def stop(self) -> None:
        """Stop workers, killing Enhanced children but preserving their uploads."""
        self._stop.set()
        self._wake.set()
        with self._active_lock:
            processes = list(self._active.values())
        for process in processes:
            self._signal_process(process, signal.SIGTERM)
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = claim_next_queued()
            if job is None:
                self._wake.wait(timeout=5.0)
                self._wake.clear()
                continue
            self._process(job)

    def _finish(self, job_id: str, status: JobStatus, **kw) -> bool:
        """Commit a terminal state, discarding output if cancel/delete won."""
        try:
            set_status(job_id, status, **kw)
            return True
        except KeyError:
            log.info("job %s vanished before %s; skipping", job_id, status)
            self._discard_output(kw.get("md_path"))
        except InvalidTransition as e:
            log.info("job %s completion lost a state race: %s", job_id, e)
            self._discard_output(kw.get("md_path"))
        return False

    @staticmethod
    def _discard_output(md_path: str | None) -> None:
        if not md_path:
            return
        try:
            Path(md_path).unlink(missing_ok=True)
        except OSError:
            log.warning("could not delete orphaned file %s", md_path)

    @staticmethod
    def _process_tree_exited(process: subprocess.Popen[bytes]) -> bool:
        process.poll()  # reap an exited group leader before probing its group
        if os.name != "posix":
            return process.returncode is not None
        try:
            os.killpg(process.pid, 0)
        except OSError as e:
            if e.errno == errno.ESRCH:
                return True
            if e.errno == errno.EPERM:
                return False
            raise
        return False

    @classmethod
    def _wait_for_exit(
        cls,
        process: subprocess.Popen[bytes],
        timeout: float,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while not cls._process_tree_exited(process) and time.monotonic() < deadline:
            time.sleep(0.02)
        return cls._process_tree_exited(process)

    @staticmethod
    def _signal_process(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        try:
            if os.name == "posix":
                # Enhanced children start a new session, so their PID remains
                # the PGID even after the leader exits. Always signal that group.
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                process.send_signal(sig)
        except ProcessLookupError:
            pass

    def _terminate_process(self, process: subprocess.Popen[bytes]) -> None:
        self._signal_process(process, signal.SIGTERM)
        if not self._wait_for_exit(process, self._terminate_grace):
            if os.name == "posix":
                self._signal_process(process, signal.SIGKILL)
            else:
                process.kill()
            self._wait_for_exit(process, self._terminate_grace)

    @staticmethod
    def _read_outcome(result_path: Path) -> tuple[str, str | None]:
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return (
                "unexpected_error",
                f"Enhanced conversion process returned no result: {e}",
            )
        kind = payload.get("kind")
        message = payload.get("message")
        if not isinstance(kind, str):
            return (
                "unexpected_error",
                "Enhanced conversion process returned an invalid result.",
            )
        return kind, message if isinstance(message, str) else None

    def _process_enhanced(self, job: Job, src: Path) -> bool:
        """Run a killable Enhanced child; return whether shutdown must preserve input."""
        current = get_job(job.id)
        if current is None or current.status != JobStatus.PROCESSING:
            return False

        token = uuid.uuid4().hex
        final_output = markdown_path(job.id)
        temp_output = final_output.with_name(f".{job.id}.{token}.md.tmp")
        result_path = final_output.with_name(f".{job.id}.{token}.result.json")
        process: subprocess.Popen[bytes] | None = None

        try:
            process = subprocess.Popen(
                self._command_factory(src, temp_output, result_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            with self._active_lock:
                self._active[job.id] = process

            while process.poll() is None:
                current = get_job(job.id)
                if self._stop.is_set():
                    self._terminate_process(process)
                    break
                if current is None or current.status != JobStatus.PROCESSING:
                    self._terminate_process(process)
                    break
                self._stop.wait(self._poll_interval)

            if self._stop.is_set():
                return True

            current = get_job(job.id)
            if current is None or current.status != JobStatus.PROCESSING:
                return False

            kind, message = self._read_outcome(result_path)
            if kind == "ok" and temp_output.exists():
                try:
                    os.replace(temp_output, final_output)
                except OSError as e:
                    self._finish(
                        job.id,
                        JobStatus.FAILED,
                        error=f"Could not save converted Markdown: {e}",
                    )
                    return False
                if self._finish(
                    job.id,
                    JobStatus.DONE,
                    md_path=str(final_output),
                ):
                    log.info(
                        "converted Enhanced job %s (%s)", job.id, job.orig_filename
                    )
            else:
                error = message or "Enhanced conversion process failed unexpectedly."
                self._finish(job.id, JobStatus.FAILED, error=error)
                log.warning("Enhanced job %s failed: %s", job.id, error)
            return False
        except OSError as e:
            self._finish(
                job.id,
                JobStatus.FAILED,
                error=f"Could not start Enhanced conversion: {e}",
            )
            return False
        finally:
            if process is not None:
                self._terminate_process(process)
                with self._active_lock:
                    if self._active.get(job.id) is process:
                        self._active.pop(job.id, None)
            self._discard_output(str(temp_output))
            self._discard_output(str(result_path))
            current_after = get_job(job.id)
            if current_after is None or current_after.status != JobStatus.DONE:
                self._discard_output(str(final_output))

    def _process(self, job: Job) -> None:
        src = upload_path(job.id, job.file_type)
        enhanced_document = (
            job.mode == ConversionMode.ENHANCED
            and job.file_type not in AUDIO_EXTENSIONS
        )
        preserve_upload = False
        try:
            if enhanced_document:
                preserve_upload = self._process_enhanced(job, src)
                return

            text = convert(src, enhanced=False)
            output = markdown_path(job.id)
            output.write_text(text, encoding="utf-8")
            if self._finish(job.id, JobStatus.DONE, md_path=str(output)):
                log.info("converted job %s (%s)", job.id, job.orig_filename)
        except ConversionError as e:
            self._finish(job.id, JobStatus.FAILED, error=str(e))
            log.warning("job %s failed: %s", job.id, e)
        except Exception as e:  # noqa: BLE001 - never let a bad file kill the thread
            self._finish(job.id, JobStatus.FAILED, error=f"Unexpected error: {e}")
            log.exception("job %s crashed unexpectedly", job.id)
        finally:
            if not preserve_upload:
                try:
                    src.unlink(missing_ok=True)
                except OSError:
                    log.warning("could not delete original upload for job %s", job.id)


worker = Worker()
