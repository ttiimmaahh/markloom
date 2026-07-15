# Configuration

All configuration is via environment variables. In Docker, set them under
`environment:` in `compose.yaml`, or use an `.env` file (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `/data` | Root for the SQLite db and converted Markdown. Mount this as a volume so data survives restarts. |
| `RETENTION_DAYS` | `30` | Auto-delete conversions older than this many days. `0` disables expiry (keep forever). |
| `MAX_UPLOAD_MB` | `50` | Reject uploads larger than this. |
| `ALLOWED_EXTENSIONS` | `pdf,docx,pptx,xlsx,xls,html,htm,csv,json,xml,txt,md,epub` | Comma-separated file extensions the service accepts. Must be backed by a matching MarkItDown extra (see below). |
| `WORKER_THREADS` | `2` | Number of concurrent conversion threads. |
| `MAX_ATTEMPTS` | `3` | How many times an interrupted job is retried after a restart before it is failed (poison-pill guard). |
| `AUTH_USERNAME` | _(unset)_ | Set together with `AUTH_PASSWORD` to require an HTTP Basic login. |
| `AUTH_PASSWORD` | _(unset)_ | Set together with `AUTH_USERNAME` to require an HTTP Basic login. |
| `LLM_BASE_URL` | _(unset)_ | OpenAI-compatible API base URL (e.g. `https://api.openai.com/v1`, or a local server). Optional. |
| `LLM_API_KEY` | _(unset)_ | API key for the LLM endpoint. Set with `LLM_MODEL` to enable image descriptions. |
| `LLM_MODEL` | _(unset)_ | Vision-capable model name (e.g. `gpt-4o-mini`). Set with `LLM_API_KEY` to enable. |

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

## Adding more file formats

Supported formats are the intersection of two things:

1. `ALLOWED_EXTENSIONS` — the extensions the API will accept.
2. The MarkItDown extras installed in `backend/requirements.txt`
   (e.g. `markitdown[pdf,docx,pptx,xlsx,xls]`).

To add a format, add its MarkItDown extra to `requirements.txt` **and** its
extension to `ALLOWED_EXTENSIONS`, then rebuild the image. Some extras (audio,
image OCR) also require system packages — add those to the `Dockerfile`.
