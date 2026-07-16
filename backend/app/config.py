"""Application configuration, sourced from environment variables.

Every knob here maps to an entry in `.env.example`, so self-hosters can
configure the service without touching code. Defaults target the baseline we
agreed on: trusted-LAN homelab, no auth, 30-day retention.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Version ---
    # Baked into the Docker image at build time from the release tag (see
    # publish.yml's build-args). "dev" everywhere else; shown in the UI footer.
    app_version: str = "dev"

    # --- Storage ---
    # Root for the SQLite db + converted markdown. Mounted as a volume in compose.
    data_dir: Path = Path("/data")

    # --- Retention ---
    # Auto-delete converted files older than this many days. 0 = keep forever.
    retention_days: int = 30

    # --- Uploads ---
    max_upload_mb: int = 50
    # Comma-separated list; parsed into `allowed_ext_set` below. The audio types
    # (mp3/wav/m4a/ogg/flac) are transcribed, not text-extracted — see converter.py.
    allowed_extensions: str = (
        "pdf,docx,pptx,xlsx,xls,html,htm,csv,json,xml,txt,md,epub,"
        "mp3,wav,m4a,ogg,flac"
    )

    # --- Worker ---
    # Concurrent conversion threads (MarkItDown is sync/CPU-bound; see worker.py).
    worker_threads: int = 2
    # Max processing attempts before a job is failed. Crash recovery re-queues an
    # interrupted job until this many attempts are used up (poison-pill guard).
    max_attempts: int = 3

    # --- Optional basic auth (mazanoke-style) ---
    # Set BOTH to require login. Leave blank for open access (trusted LAN only).
    auth_username: str | None = None
    auth_password: str | None = None

    # --- Audio transcription ---
    # Dropped audio (mp3/wav/m4a/ogg/flac) is transcribed to a Markdown transcript.
    # By default this runs a LOCAL faster-whisper model — private, no external
    # service, no config required. `whisper_model` picks the bundled model size
    # (tiny|base|small|medium|large-v3); larger = more accurate but slower. The
    # weights download once on first use into DATA_DIR/models (persisted volume).
    whisper_model: str = "base"

    # Optional BYO transcription: an OpenAI-compatible /v1/audio/transcriptions
    # endpoint. Set audio_base_url + audio_model to route audio there INSTEAD of
    # the local whisper (e.g. to offload to a GPU box). audio_api_key is optional
    # for a local server. See `audio_api_enabled` below.
    audio_base_url: str | None = None
    audio_api_key: str | None = None
    audio_model: str | None = None

    # --- Optional LLM enhancement (OpenAI-compatible) ---
    # When llm_api_key and llm_model are both set, MarkItDown uses this model to
    # describe images it encounters (adds alt-text). Bring your own key; any
    # OpenAI-compatible endpoint works (OpenAI, a local Ollama/LM Studio server,
    # a gateway, ...) via llm_base_url. Leave unset to disable (default).
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    # --- Derived paths ---
    @property
    def db_path(self) -> Path:
        return self.data_dir / "markloom.db"

    @property
    def markdown_dir(self) -> Path:
        return self.data_dir / "markdown"

    @property
    def upload_dir(self) -> Path:
        # Originals live here only transiently, until the worker converts them.
        return self.data_dir / "uploads"

    @property
    def allowed_ext_set(self) -> set[str]:
        return {
            e.strip().lower().lstrip(".")
            for e in self.allowed_extensions.split(",")
            if e.strip()
        }

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_username and self.auth_password)

    @property
    def audio_api_enabled(self) -> bool:
        # BYO transcription is on when a model plus a base URL are set (mirrors
        # llm_enabled: a local server needs no key). Otherwise audio falls back to
        # the always-available bundled whisper.
        return bool(self.audio_model and self.audio_base_url)

    @property
    def llm_enabled(self) -> bool:
        # A model plus either a key (hosted API, e.g. OpenAI) or a base URL (a
        # local server that needs no key) is enough to turn the feature on.
        return bool(self.llm_model and (self.llm_api_key or self.llm_base_url))


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — reads the environment once per process."""
    return Settings()
