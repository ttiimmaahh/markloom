"""Schema migration: adding a column to the code must not break existing DBs.

`CREATE TABLE IF NOT EXISTS` never alters an existing table, so every new column
needs an ADD COLUMN migration. These tests guard that.
"""

import sqlite3

from app.db import _COLUMN_MIGRATIONS, _migrate


def _old_db() -> sqlite3.Connection:
    # A minimal pre-migration jobs table missing `attempts` and `mode`.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL);")
    return conn


def test_migrate_adds_all_missing_columns():
    conn = _old_db()
    _migrate(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    for column in _COLUMN_MIGRATIONS:
        assert column in cols, f"{column} was not added"


def test_migrate_is_idempotent():
    conn = _old_db()
    _migrate(conn)
    _migrate(conn)  # second pass must be a no-op, not an error
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert "mode" in cols


def test_legacy_db_filename_rename(tmp_path):
    """A pre-rename markitdown.db (and its WAL) migrates to markloom.db in place."""
    from app.db import _rename_legacy_db

    class _Settings:
        data_dir = tmp_path
        db_path = tmp_path / "markloom.db"

    (tmp_path / "markitdown.db").write_text("db")
    (tmp_path / "markitdown.db-wal").write_text("wal")

    _rename_legacy_db(_Settings())

    assert (tmp_path / "markloom.db").read_text() == "db"
    assert (tmp_path / "markloom.db-wal").read_text() == "wal"
    assert not (tmp_path / "markitdown.db").exists()
