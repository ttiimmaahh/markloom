"""MarkItDown wrappers: a fast standard engine and an LLM-OCR enhanced engine.

- Standard: plain MarkItDown() — deterministic text extraction, no LLM. Fast and
  faithful; the default for every conversion.
- Enhanced: MarkItDown(enable_plugins=True, llm_client=..., llm_model=...) — the
  markitdown-ocr plugin OCRs images embedded in PDF/DOCX/PPTX/XLSX (and the
  built-in image converter handles standalone images) using the configured
  vision LLM. Slower; only offered when an LLM is configured.

Both engines are built lazily so importing this module needs neither MarkItDown
nor openai installed.
"""
from __future__ import annotations

from pathlib import Path

# A prompt tuned for faithful OCR rather than loose image captioning: transcribe
# verbatim, keep tables as Markdown, and stay silent on empty images (reduces the
# "invent plausible text" failure mode weaker models exhibit).
OCR_PROMPT = (
    "Transcribe all text visible in this image exactly as it appears. "
    "Preserve reading order and render any tables as Markdown tables. "
    "Output only the transcribed text — no descriptions, no commentary. "
    "If the image contains no legible text, output nothing."
)


class ConversionError(Exception):
    """A clean, user-facing conversion failure (wraps MarkItDown's internals)."""


_standard_engine = None
_enhanced_engine = None


def _standard():
    global _standard_engine
    if _standard_engine is None:
        from markitdown import MarkItDown

        _standard_engine = MarkItDown()
    return _standard_engine


def _enhanced():
    global _enhanced_engine
    if _enhanced_engine is None:
        from markitdown import MarkItDown
        from openai import OpenAI

        from .config import get_settings

        settings = get_settings()
        client = OpenAI(
            api_key=settings.llm_api_key or "not-needed",
            base_url=settings.llm_base_url or None,
        )
        _enhanced_engine = MarkItDown(
            enable_plugins=True,
            llm_client=client,
            llm_model=settings.llm_model,
            llm_prompt=OCR_PROMPT,
        )
    return _enhanced_engine


def convert(src_path: str | Path, *, enhanced: bool = False) -> str:
    """Convert a file to Markdown, or raise ConversionError with a clean message."""
    engine = _enhanced() if enhanced else _standard()
    try:
        result = engine.convert(str(src_path))
    except Exception as e:  # MarkItDown raises a variety of dependency-specific errors
        raise ConversionError(f"Could not convert file: {e}") from e

    text = getattr(result, "text_content", None)
    if text is None:
        text = getattr(result, "markdown", None)
    if text is None:
        raise ConversionError("Conversion produced no text output.")
    return text
