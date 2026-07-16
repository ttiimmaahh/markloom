"""Auto-expire scheduler.

A daily APScheduler job purges jobs older than RETENTION_DAYS and unlinks their
Markdown files. Disabled automatically when retention is <= 0 (keep forever).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from .config import get_settings
from .jobs import purge_expired

log = logging.getLogger("markloom.cleanup")

_scheduler: BackgroundScheduler | None = None


def sweep() -> None:
    """Delete expired job rows and their Markdown files."""
    settings = get_settings()
    purged = purge_expired(settings.retention_days)
    for job in purged:
        if job.md_path:
            try:
                Path(job.md_path).unlink(missing_ok=True)
            except OSError:
                log.warning("could not delete md file %s", job.md_path)
    if purged:
        log.info("cleanup purged %d expired job(s)", len(purged))


def start() -> None:
    global _scheduler
    settings = get_settings()
    if settings.retention_days <= 0:
        log.info("retention disabled (RETENTION_DAYS<=0); cleanup not scheduled")
        return
    _scheduler = BackgroundScheduler(daemon=True)
    # next_run_time=now: an interval trigger's first fire is otherwise one full
    # interval after start, so a container restarted more often than every 24h
    # would NEVER sweep. Running once at startup makes retention restart-proof.
    _scheduler.add_job(
        sweep, "interval", hours=24, id="cleanup", next_run_time=datetime.now()
    )
    _scheduler.start()
    log.info("cleanup scheduled every 24h (retention=%d days)", settings.retention_days)


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
