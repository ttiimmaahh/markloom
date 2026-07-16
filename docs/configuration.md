# Configuration

All configuration is via environment variables. In Docker, set them under
`environment:` in `compose.yaml`, or use an `.env` file (see `.env.example`).

| Variable | Default | Description |
| --- | --- | --- |
| `PUID` | `1000` | Numeric host user ID used by Compose for the app process and `./data` ownership. |
| `PGID` | `1000` | Numeric host group ID used by Compose for the app process and `./data` ownership. |
| `DATA_DIR` | `/data` | Root for the SQLite db and converted Markdown. Mount this as a volume so data survives restarts. |
| `RETENTION_DAYS` | `30` | Auto-delete conversions older than this many days. `0` disables expiry (keep forever). |
| `MAX_UPLOAD_MB` | `50` | Reject uploads larger than this. |
| `ALLOWED_EXTENSIONS` | `pdf,docx,…,epub,mp3,wav,m4a,ogg,flac` | Comma-separated file extensions the service accepts. Document types must be backed by a matching MarkItDown extra (see below); audio types are transcribed (see [Audio transcription](#audio-transcription)). |
| `WORKER_THREADS` | `2` | Number of concurrent conversion threads. |
| `MAX_ATTEMPTS` | `3` | How many times an interrupted job is retried after a restart before it is failed (poison-pill guard). |
| `WHISPER_MODEL` | `base` | Bundled local transcription model size: `tiny`, `base`, `small`, `medium`, `large-v3`. Larger = more accurate but slower. Weights download once into `DATA_DIR/models`. |
| `AUDIO_BASE_URL` | _(unset)_ | Optional. OpenAI-compatible `/v1/audio/transcriptions` base URL. Set with `AUDIO_MODEL` to transcribe via a remote service instead of the local model. |
| `AUDIO_API_KEY` | _(unset)_ | API key for the transcription endpoint. Optional for a local server. |
| `AUDIO_MODEL` | _(unset)_ | Transcription model name (e.g. `whisper-1`). Set with `AUDIO_BASE_URL` to enable BYO transcription. |
| `AUTH_USERNAME` | _(unset)_ | Set together with `AUTH_PASSWORD` to require an HTTP Basic login. |
| `AUTH_PASSWORD` | _(unset)_ | Set together with `AUTH_USERNAME` to require an HTTP Basic login. |
| `LLM_BASE_URL` | _(unset)_ | OpenAI-compatible API base URL (e.g. `https://api.openai.com/v1`, or a local server). Optional. |
| `LLM_API_KEY` | _(unset)_ | API key for the LLM endpoint. Set with `LLM_MODEL` to enable image descriptions. |
| `LLM_MODEL` | _(unset)_ | Vision-capable model name (e.g. `gpt-4o-mini`). Set with `LLM_API_KEY` to enable. |

Markloom supports one application process per `DATA_DIR`, as configured by the
provided Docker image. Do not add multiple Uvicorn workers or run multiple
containers against the same SQLite database: startup recovery assumes any
`processing` row belongs to an interrupted process.

## Enabling authentication

The service is **open by default** — fine on a trusted LAN, unsafe on the public
internet. Set both credential variables to require a login:

```yaml
services:
  markloom:
    image: ghcr.io/ttiimmaahh/markloom:latest
    ports:
      - "8674:8000"
    volumes:
      - ./data:/data
    environment:
      - AUTH_USERNAME=admin
      - AUTH_PASSWORD=a-long-random-password
    restart: unless-stopped
```

When both are set, every request (except the `/api/health` probe) requires the
credentials. If either is missing, auth is disabled.

> [!NOTE]
> Basic auth is sent by the browser on every request once entered, including
> requests triggered by other sites (CSRF). Markloom's API is low-stakes (a
> malicious page could at worst submit a conversion), but if you expose it
> beyond your LAN, put it behind a reverse proxy with TLS — Basic credentials
> are plaintext over HTTP.

## File permissions

Markloom runs as a non-root user. The provided Compose files start a short-lived
`markloom-permissions` service as root with access only to the data mount. It
creates Docker's missing `./data` bind source when necessary, changes its
ownership to `PUID:PGID`, exits, and only then starts the non-root application.
This makes a first run and an upgrade from an older root-running image work
without a manual `chown`.

`PUID` and `PGID` default to `1000`. Compose reads overrides from the shell or the
project's `.env` file. On a host where your account uses different IDs:

```bash
PUID=$(id -u) PGID=$(id -g) docker compose up -d
```

These variables are Compose controls, not passive application settings: the init
service applies the ownership and the main service runs with the same numeric
identity. A custom `docker run` command or Compose file that omits the init
service must instead use a named volume or pre-create/chown its bind directory.

## Optional LLM — "Enhanced" conversion

Configuring an LLM unlocks an opt-in **Enhanced** conversion mode in the UI. When
a user ticks it for an upload, MarkItDown uses the model to **OCR text out of
images** embedded in PDF/DOCX/PPTX/XLSX (screenshots, diagrams, scans) — content
the fast Standard mode can't see. Standard remains the default for every file.

The model **must be vision-capable**; a text-only model will hallucinate. Any
OpenAI-compatible endpoint works, including a local server so nothing leaves your
machine:

```yaml
    environment:
      # OpenAI:
      - LLM_BASE_URL=https://api.openai.com/v1
      - LLM_API_KEY=sk-...
      - LLM_MODEL=gpt-4o-mini
      # ...or a local vision server (no key needed):
      # - LLM_BASE_URL=http://host.docker.internal:8080/v1
      # - LLM_MODEL=mlx-community/Qwen2.5-VL-7B-Instruct-4bit
```

Enhanced is **much slower** (a model call per embedded image) and **may contain
OCR errors** — great for making screenshots searchable, not a verbatim record.
It does **not** reconstruct born-digital PDF tables/layout (that's Azure Document
Intelligence). See [conversion-quality.md](conversion-quality.md) for details.

Queued conversions and active Enhanced document conversions expose a **Stop**
action in history. Enhanced work runs in a supervised child process, so stopping
it terminates Markloom's local request and prevents any result from being
committed. A remote provider that ignores client disconnects may continue to
completion and may still charge for that work. Standard and audio conversions
run in-process and can only be stopped while they are still queued.

## Audio transcription

Drop an audio file (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`) and Markloom returns a
**timestamped Markdown transcript**:

```markdown
**[0:00]** Hello and welcome to the show.

**[0:05]** Today we're talking about self-hosting your own tools.
```

This works out of the box with **no configuration** — a local
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) model runs
in-process on CPU, so audio never leaves your machine and no LLM is required.
The model weights (~150 MB for `base`) download **once on first use** into
`DATA_DIR/models`, so mount that volume to avoid re-downloading on every restart.
Pick accuracy vs. speed with `WHISPER_MODEL` (`tiny`…`large-v3`).

> Transcripts are machine-generated and may contain errors — verify critical
> details against the audio.

### Bring your own transcription endpoint

To offload transcription (e.g. to a GPU box) instead of running it locally, point
Markloom at any OpenAI-compatible `/v1/audio/transcriptions` endpoint:

```yaml
    environment:
      - AUDIO_BASE_URL=https://api.openai.com/v1
      - AUDIO_API_KEY=sk-...
      - AUDIO_MODEL=whisper-1
      # ...or a local server (no key needed):
      # - AUDIO_BASE_URL=http://host.docker.internal:8080/v1
      # - AUDIO_MODEL=whisper-1
```

When both `AUDIO_BASE_URL` and `AUDIO_MODEL` are set, audio is sent there instead
of to the bundled model. Timestamps come from the endpoint's `verbose_json`
response; a server that doesn't support segments yields a single untimed block.

## Adding more file formats

Supported formats are the intersection of two things:

1. `ALLOWED_EXTENSIONS` — the extensions the API will accept.
2. The MarkItDown extras installed in `backend/requirements.txt`
   (e.g. `markitdown[pdf,docx,pptx,xlsx,xls]`).

To add a format, add its MarkItDown extra to `requirements.txt` **and** its
extension to `ALLOWED_EXTENSIONS`, then rebuild the image. Some extras (audio,
image OCR) also require system packages — add those to the `Dockerfile`.
