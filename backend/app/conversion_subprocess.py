"""Isolated Enhanced conversion entry point.

The worker launches this module in a child process so a stuck MarkItDown/OpenAI
request can be terminated without killing the API process. The child owns only
conversion and a temporary Markdown file; the parent remains authoritative for
SQLite state and promotion to the final output path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .converter import ConversionError, convert

_MAX_ERROR_LENGTH = 4_000


def _write_result(result_path: Path, kind: str, message: str | None = None) -> None:
    payload = {"kind": kind}
    if message:
        payload["message"] = message[:_MAX_ERROR_LENGTH]
    result_path.write_text(json.dumps(payload), encoding="utf-8")


def run_conversion(src_path: Path, output_path: Path, result_path: Path) -> None:
    """Convert one document and persist a small outcome envelope for the parent."""
    try:
        text = convert(src_path, enhanced=True)
        output_path.write_text(text, encoding="utf-8")
        _write_result(result_path, "ok")
    except ConversionError as e:
        _write_result(result_path, "conversion_error", str(e))
    except Exception as e:  # noqa: BLE001 - isolate every plugin/provider failure
        _write_result(result_path, "unexpected_error", f"Unexpected error: {e}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    run_conversion(args.src, args.output, args.result)


if __name__ == "__main__":
    main()
