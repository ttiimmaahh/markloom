"""Audio transcription: routing, engine selection, and transcript rendering.

These tests are network-free by design: the real faster-whisper model would
download weights on first use, so we monkeypatch the two transcription paths and
assert the *dispatch* logic instead. The genuine end-to-end run (local whisper on
a real clip) is done manually — see the audio feature notes.
"""
from pathlib import Path

import pytest

from app import converter
from app.config import Settings


def test_audio_extensions_allowed_by_default():
    exts = Settings().allowed_ext_set
    for a in ("mp3", "wav", "m4a", "ogg", "flac"):
        assert a in exts, f"{a} should be accepted out of the box"


def test_format_timestamp():
    assert converter._format_timestamp(0) == "0:00"
    assert converter._format_timestamp(4.9) == "0:04"       # truncates, not rounds
    assert converter._format_timestamp(75) == "1:15"
    assert converter._format_timestamp(3661) == "1:01:01"    # rolls over to H:MM:SS


def test_render_transcript_timestamps_and_skips_empty():
    md = converter._render_transcript([(0.0, "Hello there."), (5.0, "   "), (9.0, " Second. ")])
    assert md == "**[0:00]** Hello there.\n\n**[0:09]** Second.\n"


def test_render_transcript_all_empty_raises():
    with pytest.raises(converter.ConversionError):
        converter._render_transcript([(0.0, "   "), (2.0, "")])


def test_convert_routes_audio_to_transcription(monkeypatch):
    # An audio extension must NOT touch MarkItDown — it goes to _transcribe.
    called = {}

    def fake_transcribe(path):
        called["path"] = path
        return "**[0:00]** transcript\n"

    def boom(*_a, **_k):
        raise AssertionError("MarkItDown must not be used for audio")

    monkeypatch.setattr(converter, "_transcribe", fake_transcribe)
    monkeypatch.setattr(converter, "_standard", boom)
    monkeypatch.setattr(converter, "_enhanced", boom)

    out = converter.convert("clip.mp3")
    assert out == "**[0:00]** transcript\n"
    assert called["path"] == Path("clip.mp3")


def test_convert_non_audio_still_uses_markitdown(monkeypatch):
    monkeypatch.setattr(converter, "_transcribe", lambda p: (_ for _ in ()).throw(
        AssertionError("non-audio must not be transcribed")))

    class _Result:
        text_content = "# ok"

    monkeypatch.setattr(converter, "_standard", lambda: type("E", (), {"convert": lambda self, p: _Result()})())
    assert converter.convert("doc.html") == "# ok"


class _StubSettings:
    def __init__(self, api_enabled: bool):
        self.audio_api_enabled = api_enabled


def test_transcribe_selects_api_when_configured(monkeypatch):
    # _transcribe imports get_settings from app.config at call time, so patching
    # the attribute there controls which path it picks.
    from app import config

    monkeypatch.setattr(converter, "_transcribe_api", lambda p: [(0.0, "from api")])
    monkeypatch.setattr(converter, "_transcribe_local", lambda p: [(0.0, "from local")])

    monkeypatch.setattr(config, "get_settings", lambda: _StubSettings(True))
    assert "from api" in converter._transcribe(Path("x.mp3"))

    monkeypatch.setattr(config, "get_settings", lambda: _StubSettings(False))
    assert "from local" in converter._transcribe(Path("x.mp3"))
