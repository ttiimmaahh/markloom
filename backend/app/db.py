"""SQLite connection management and schema initialization.

Design notes:
- WAL mode is enabled so the background worker thread and the API request
  handlers can read/write concurrently without "database is locked" errors
  under normal single-user load.
- There is exactly one table, `jobs`. It is the contract between the API
  (producer), the worker (consumer), and the cleanup scheduler. The state
  machine that governs its `status` column lives in jobs.py.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,   -- uuid; also the public download handle
    orig_filename TEXT NOT NULL,      -- what the user dropped
    file_type     TEXT NOT NULL,      -- extension: pdf, docx, ...
    size_bytes    INTEGER NOT NULL,
    status        TEXT NOT NULL,      -- queued | processing | done | failed
    mode          TEXT NOT NULL DEFAULT 'standard',  -- standard | enhanced (LLM OCR)
    attempts      INTEGER NOT NULL DEFAULT 0,  -- processing attempts (poison-pill guard)
    error         TEXT,               -- message when status = failed
    md_path       TEXT,               -- path under DATA_DIR once status = done
    created_at    TEXT NOT NULL,      -- ISO-8601 UTC; drives auto-expire
    completed_at  TEXT                -- ISO-8601 UTC; set on done/failed
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
"""

# Columns added after the very first schema. On startup we ADD COLUMN any that a
# pre-existing database is missing — `CREATE TABLE IF NOT EXISTS` never alters an
# existing table, so without this an old DB crashes when new code reads new columns.
# Each DDL must be a self-contained `ALTER TABLE jobs ADD COLUMN ...` with a DEFAULT
# (required by SQLite for NOT NULL columns on existing rows).
_COLUMN_MIGRATIONS = {
    "attempts": "ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
    "mode": "ALTER TABLE jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'standard'",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for column, ddl in _COLUMN_MIGRATIONS.items():
        if column not in existing:
            conn.execute(ddl)


def _rename_legacy_db(settings) -> None:
    """One-time: migrate a pre-rename `markitdown.db` to `markloom.db` in place.

    Preserves history from before the project was renamed to Markloom. Renames the
    WAL/SHM sidecars too. No-op once the new file exists.
    """
    new = settings.db_path
    old = new.parent / "markitdown.db"
    if old.exists() and not new.exists():
        for suffix in ("", "-wal", "-shm"):
            src = old.parent / (old.name + suffix)
            if src.exists():
                src.rename(new.parent / (new.name + suffix))


def init_db() -> None:
    """Create data directories, the jobs table, and migrate missing columns.

    Idempotent; safe to call on every startup. Preserves existing rows.
    """
    settings = get_settings()
    for d in (settings.data_dir, settings.markdown_dir, settings.upload_dir):
        d.mkdir(parents=True, exist_ok=True)
    _rename_legacy_db(settings)
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA)
        _migrate(conn)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield a connection, committing on success and rolling back on error.

    `timeout=30` lets a writer wait out a concurrent write instead of erroring
    immediately — important with a worker thread and API sharing the file.
    """
    settings = get_settings()
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
