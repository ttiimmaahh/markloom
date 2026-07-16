from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from app import jobs as jobs_module
from app.db import get_connection, init_db
from app.jobs import (
    ConversionMode,
    InvalidTransition,
    Job,
    JobStatus,
    cancel_job,
    create_job,
    delete_job,
    get_job,
    purge_expired,
    recover_interrupted_jobs,
    set_status,
)
from app.storage import markdown_path, upload_path
from app.worker import Worker


@pytest.fixture(autouse=True)
def database():
    init_db()


@pytest.fixture
def jobs_to_clean():
    ids: list[str] = []
    yield ids
    for job_id in ids:
        job = delete_job(job_id)
        if job is not None:
            upload_path(job.id, job.file_type).unlink(missing_ok=True)
            markdown_path(job.id).unlink(missing_ok=True)


def _create(*, mode: ConversionMode = ConversionMode.ENHANCED) -> Job:
    return create_job("input.pdf", "pdf", 4, mode=mode)


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def _require_job(job_id: str) -> Job:
    job = get_job(job_id)
    if job is None:
        raise AssertionError(f"job {job_id} unexpectedly missing")
    return job


def _start_blocking_job(
    job: Job,
    *,
    ignore_sigterm: bool = False,
) -> tuple[Worker, threading.Thread, dict[str, Path]]:
    set_status(job.id, JobStatus.PROCESSING)
    src = upload_path(job.id, job.file_type)
    src.write_bytes(b"pdf")
    paths: dict[str, Path] = {}

    def command_factory(_src: Path, output: Path, result: Path) -> list[str]:
        paths.update(output=output, result=result)
        setup = (
            "import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            if ignore_sigterm
            else ""
        )
        script = setup + (
            "from pathlib import Path; import sys, time; "
            "Path(sys.argv[1]).write_text('ready'); time.sleep(60)"
        )
        return [sys.executable, "-c", script, str(result)]

    worker = Worker(
        poll_interval=0.01,
        terminate_grace=0.05,
        command_factory=command_factory,
    )
    thread = threading.Thread(target=worker._process, args=(_require_job(job.id),))
    thread.start()
    _wait_until(lambda: paths.get("result", Path("/missing")).exists())
    return worker, thread, paths


def _run_scripted_job(job: Job, script: str) -> Worker:
    set_status(job.id, JobStatus.PROCESSING)
    upload_path(job.id, job.file_type).write_bytes(b"pdf")

    def command_factory(_src: Path, output: Path, result: Path) -> list[str]:
        return [sys.executable, "-c", script, str(output), str(result)]

    worker = Worker(
        poll_interval=0.01,
        terminate_grace=0.05,
        command_factory=command_factory,
    )
    worker._process(_require_job(job.id))
    return worker


def test_queued_cancel_is_terminal_and_idempotent(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)

    canceled = cancel_job(job.id)

    assert canceled.status == JobStatus.CANCELED
    assert canceled.completed_at is not None
    assert canceled.error is None
    assert canceled.md_path is None
    assert cancel_job(job.id).status == JobStatus.CANCELED


def test_cancel_and_completion_cannot_overwrite_each_other(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    set_status(job.id, JobStatus.PROCESSING)

    def finish(target: JobStatus):
        try:
            return set_status(job.id, target)
        except InvalidTransition:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(finish, (JobStatus.DONE, JobStatus.CANCELED)))

    assert sum(map(bool, outcomes)) == 1
    assert _require_job(job.id).status in {JobStatus.DONE, JobStatus.CANCELED}


def test_processing_standard_job_is_not_killable(jobs_to_clean):
    job = _create(mode=ConversionMode.STANDARD)
    jobs_to_clean.append(job.id)
    set_status(job.id, JobStatus.PROCESSING)

    with pytest.raises(InvalidTransition):
        cancel_job(job.id)


def test_claim_race_does_not_cancel_processing_standard_job(
    jobs_to_clean,
    monkeypatch,
):
    job = _create(mode=ConversionMode.STANDARD)
    jobs_to_clean.append(job.id)
    original_get_job = jobs_module.get_job
    interposed = False

    def get_job_after_claim(job_id: str):
        nonlocal interposed
        snapshot = original_get_job(job_id)
        if not interposed:
            interposed = True
            jobs_module.claim_next_queued()
        return snapshot

    monkeypatch.setattr(jobs_module, "get_job", get_job_after_claim)
    with pytest.raises(InvalidTransition):
        cancel_job(job.id)

    assert _require_job(job.id).status == JobStatus.PROCESSING


def test_claim_race_still_cancels_processing_enhanced_job(
    jobs_to_clean,
    monkeypatch,
):
    job = _create()
    jobs_to_clean.append(job.id)
    original_get_job = jobs_module.get_job
    interposed = False

    def get_job_after_claim(job_id: str):
        nonlocal interposed
        snapshot = original_get_job(job_id)
        if not interposed:
            interposed = True
            jobs_module.claim_next_queued()
        return snapshot

    monkeypatch.setattr(jobs_module, "get_job", get_job_after_claim)

    assert cancel_job(job.id).status == JobStatus.CANCELED


def test_enhanced_child_success_promotes_output(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    script = (
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_text('# converted'); "
        'Path(sys.argv[2]).write_text(\'{"kind": "ok"}\')'
    )

    _run_scripted_job(job, script)

    settled = _require_job(job.id)
    assert settled.status == JobStatus.DONE
    assert markdown_path(job.id).read_text() == "# converted"
    assert not upload_path(job.id, job.file_type).exists()


def test_enhanced_child_error_marks_job_failed(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    script = (
        "from pathlib import Path; import sys; "
        "Path(sys.argv[2]).write_text("
        '\'{"kind": "conversion_error", "message": "provider failed"}\')'
    )

    _run_scripted_job(job, script)

    settled = _require_job(job.id)
    assert settled.status == JobStatus.FAILED
    assert settled.error == "provider failed"


def test_enhanced_spawn_failure_marks_job_failed(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    set_status(job.id, JobStatus.PROCESSING)
    upload_path(job.id, job.file_type).write_bytes(b"pdf")
    worker = Worker(command_factory=lambda *_paths: ["/missing/markloom-command"])

    worker._process(_require_job(job.id))

    settled = _require_job(job.id)
    assert settled.status == JobStatus.FAILED
    assert settled.error and "Could not start Enhanced conversion" in settled.error


def test_cancel_terminates_blocking_enhanced_process(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    worker, thread, _paths = _start_blocking_job(job)

    cancel_job(job.id)
    worker.cancel(job.id)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert _require_job(job.id).status == JobStatus.CANCELED
    assert not upload_path(job.id, job.file_type).exists()
    assert not markdown_path(job.id).exists()


def test_cancel_kills_child_that_ignores_terminate(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    worker, thread, _paths = _start_blocking_job(job, ignore_sigterm=True)

    cancel_job(job.id)
    worker.cancel(job.id)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert _require_job(job.id).status == JobStatus.CANCELED


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_cancel_terminates_enhanced_process_tree(jobs_to_clean, tmp_path):
    job = _create()
    jobs_to_clean.append(job.id)
    set_status(job.id, JobStatus.PROCESSING)
    upload_path(job.id, job.file_type).write_bytes(b"pdf")
    marker = tmp_path / "descendant-survived"
    ready: dict[str, Path] = {}

    def command_factory(_src: Path, _output: Path, result: Path) -> list[str]:
        ready["path"] = result
        child = (
            "from pathlib import Path; import signal, sys, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(0.4); "
            "Path(sys.argv[1]).write_text('survived')"
        )
        parent = (
            "from pathlib import Path; import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[3]]); "
            "Path(sys.argv[1]).write_text('ready'); time.sleep(60)"
        )
        return [sys.executable, "-c", parent, str(result), child, str(marker)]

    worker = Worker(
        poll_interval=0.01,
        terminate_grace=0.05,
        command_factory=command_factory,
    )
    thread = threading.Thread(target=worker._process, args=(_require_job(job.id),))
    thread.start()
    _wait_until(lambda: ready.get("path", Path("/missing")).exists())

    cancel_job(job.id)
    worker.cancel(job.id)
    thread.join(timeout=2)
    time.sleep(0.6)

    assert not thread.is_alive()
    assert not marker.exists()


def test_shutdown_preserves_processing_job_for_recovery(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    worker, thread, _paths = _start_blocking_job(job)

    worker.stop()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert _require_job(job.id).status == JobStatus.PROCESSING
    assert upload_path(job.id, job.file_type).exists()


def test_recovery_removes_interrupted_enhanced_artifacts(jobs_to_clean):
    job = _create()
    jobs_to_clean.append(job.id)
    set_status(job.id, JobStatus.PROCESSING)
    output = markdown_path(job.id)
    temp = output.with_name(f".{job.id}.token.md.tmp")
    result = output.with_name(f".{job.id}.token.result.json")
    for path in (output, temp, result):
        path.write_text("orphan")

    recover_interrupted_jobs()

    assert _require_job(job.id).status == JobStatus.QUEUED
    assert not output.exists()
    assert not temp.exists()
    assert not result.exists()


def test_retention_skips_active_jobs(jobs_to_clean):
    queued = _create()
    done = _create()
    jobs_to_clean.extend((queued.id, done.id))
    set_status(done.id, JobStatus.PROCESSING)
    set_status(done.id, JobStatus.DONE, md_path=str(markdown_path(done.id)))
    old = "2000-01-01T00:00:00+00:00"
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET created_at = ? WHERE id IN (?, ?)",
            (old, queued.id, done.id),
        )

    purged = purge_expired(1)

    assert [job.id for job in purged] == [done.id]
    assert get_job(queued.id) is not None
    assert get_job(done.id) is None
