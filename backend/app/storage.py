"""Filesystem path conventions, shared by the API (writer) and worker (reader).

Keeping these in one place guarantees the upload the API saves is the exact path
the worker later reads and deletes.
"""

from __future__ import annotations

from pathlib import Path

from .config import get_settings


def upload_path(job_id: str, ext: str) -> Path:
    """Where the original upload lives until the worker converts (then deletes) it."""
    return get_settings().upload_dir / f"{job_id}.{ext}"


def markdown_path(job_id: str) -> Path:
    """Where the converted Markdown is written and served from."""
    return get_settings().markdown_dir / f"{job_id}.md"
