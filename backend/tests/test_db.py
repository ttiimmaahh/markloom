"""Startup permission-error regression tests.

Since v0.2.5 the container runs as uid 1000; a root-owned data directory
(old image, or auto-created by Docker for a bind mount) makes startup fail.
init_db() must surface that as an actionable chown hint in docker logs, not a
bare PermissionError traceback.
"""
import os

import pytest

from app.config import get_settings
from app.db import init_db


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
def test_unwritable_data_dir_raises_chown_hint(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o555)  # readable, not writable — like a root-owned bind mount
    monkeypatch.setattr(get_settings(), "data_dir", data)
    try:
        with pytest.raises(RuntimeError, match="chown -R 1000:1000"):
            init_db()
    finally:
        data.chmod(0o755)  # let pytest clean up tmp_path


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
def test_readonly_db_file_raises_chown_hint(tmp_path, monkeypatch):
    # Directory writable, but the SQLite file itself isn't (chown without -R).
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(get_settings(), "data_dir", data)
    db_file = data / "markloom.db"
    db_file.touch()
    db_file.chmod(0o444)
    with pytest.raises(RuntimeError, match="chown -R 1000:1000"):
        init_db()
