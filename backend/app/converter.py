"""Conversion engines: text extraction (MarkItDown) and audio transcription.

- Standard: plain MarkItDown() — deterministic text extraction, no LLM. Fast and
  faithful; the default for every document conversion.
- Enhanced: MarkItDown(enable_plugins=True, llm_client=..., llm_model=...) — the
  markitdown-ocr plugin OCRs images embedded in PDF/DOCX/PPTX/XLSX (and the
  built-in image converter handles standalone images) using the configured
  vision LLM. Slower; only offered when an LLM is configured.
- Audio: mp3/wav/m4a/ogg/flac are TRANSCRIBED, not text-extracted. By default a
  local faster-whisper model runs in-process (private, no external service). If a
  BYO OpenAI-compatible endpoint is configured (settings.audio_api_enabled), the
  file is sent there instead. Output is a timestamped Markdown transcript.

  NOTE: we deliberately do NOT use MarkItDown's own audio path — it routes to
  `speech_recognition`, which calls Google's ONLINE API. Transcription here stays
  local by default.

Every engine is built lazily so importing this module needs none of MarkItDown,
openai, or faster-whisper installed.
"""

from __future__ import annotations

from pathlib import Path

from .config import AUDIO_EXTENSIONS

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
    """A clean, user-facing conversion failure (wraps an engine's internals)."""


_standard_engine = None
_enhanced_engine = None
_whisper_model = None


def _standard():
    global _standard_engine
    if _standard_engine is None:
        from markitdown import MarkItDown  # pyright: ignore[reportMissingImports]

        _standard_engine = MarkItDown()
    return _standard_engine


def _enhanced():
    global _enhanced_engine
    if _enhanced_engine is None:
        from markitdown import MarkItDown  # pyright: ignore[reportMissingImports]
        from openai import OpenAI  # pyright: ignore[reportMissingImports]

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


# ---------------------------------------------------------------------------
# Audio transcription
# ---------------------------------------------------------------------------
#
# Both the local and BYO-API paths normalise their output to a list of
# `(start_seconds, text)` segments, which _render_transcript() turns into a
# timestamped Markdown document. Keeping the "extract segments" and "render"
# steps separate is deliberate: adding speaker diarization later means enriching
# a segment with a speaker label, not rewriting either path.


def _format_timestamp(seconds: float) -> str:
    """Seconds -> M:SS, or H:MM:SS once the recording passes an hour."""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError, OverflowError):
        total = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _render_transcript(segments: list[tuple[float, str]]) -> str:
    """Render normalised (start, text) segments as a timestamped Markdown doc.

    Each non-empty segment becomes its own paragraph prefixed with a bold
    timestamp, e.g. `**[0:04]** ...`. Empty/whitespace-only segments are dropped.
    """
    lines = [
        f"**[{_format_timestamp(start)}]** {stripped}"
        for start, text in segments
        if (stripped := text.strip())
    ]
    if not lines:
        raise ConversionError("Transcription produced no speech.")
    return "\n\n".join(lines) + "\n"


def _transcribe_local(src_path: Path) -> list[tuple[float, str]]:
    """Transcribe with a bundled faster-whisper model (lazy, process-wide singleton)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel  # pyright: ignore[reportMissingImports]

        from .config import get_settings

        settings = get_settings()
        # int8 on CPU keeps memory/latency reasonable for a homelab box. Weights
        # cache under DATA_DIR/models so they download once and survive restarts.
        _whisper_model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",
            download_root=str(settings.data_dir / "models"),
        )
    segments, _info = _whisper_model.transcribe(str(src_path))
    return [(seg.start or 0.0, seg.text) for seg in segments]


def _transcribe_api(src_path: Path) -> list[tuple[float, str]]:
    """Transcribe via a BYO OpenAI-compatible /v1/audio/transcriptions endpoint.

    Requests `verbose_json` to recover per-segment timestamps; if the server
    doesn't support it (or returns no segments), falls back to a single segment
    holding the whole transcript at 0:00.
    """
    from openai import OpenAI  # pyright: ignore[reportMissingImports]

    from .config import get_settings

    settings = get_settings()
    audio_model = settings.audio_model
    audio_base_url = settings.audio_base_url
    if not audio_model or not audio_base_url:
        raise ConversionError("Audio transcription service is not fully configured.")
    client = OpenAI(
        api_key=settings.audio_api_key or "not-needed",
        base_url=audio_base_url,
    )
    try:
        with src_path.open("rb") as fh:
            result = client.audio.transcriptions.create(
                model=audio_model,
                file=fh,
                response_format="verbose_json",
            )
    except OSError as e:
        raise ConversionError(f"Could not read audio file: {e}") from e
    segments = getattr(result, "segments", None) or []
    normalised = [
        (getattr(seg, "start", 0.0) or 0.0, getattr(seg, "text", "") or "")
        for seg in segments
    ]
    if normalised:
        return normalised
    # No segment timestamps available — keep the transcript rather than fail.
    return [(0.0, getattr(result, "text", "") or "")]


def _transcribe(src_path: Path) -> str:
    """Transcribe an audio file to a timestamped Markdown transcript."""
    settings_use_api = None
    try:
        from .config import get_settings

        settings_use_api = get_settings().audio_api_enabled
        segments = (
            _transcribe_api(src_path)
            if settings_use_api
            else _transcribe_local(src_path)
        )
    except ConversionError:
        raise
    except Exception as e:  # any decode / model / network failure
        where = "transcription service" if settings_use_api else "local transcription"
        raise ConversionError(f"Could not transcribe audio via {where}: {e}") from e
    return _render_transcript(segments)


def convert(src_path: str | Path, *, enhanced: bool = False) -> str:
    """Convert a file to Markdown, or raise ConversionError with a clean message.

    Audio files are transcribed (the `enhanced` flag is a document-OCR concept and
    does not apply); everything else goes through MarkItDown.
    """
    src_path = Path(src_path)
    if src_path.suffix.lower().lstrip(".") in AUDIO_EXTENSIONS:
        return _transcribe(src_path)

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
