# Markloom

> Self-hostable web app that turns your documents into Markdown. Drop a file,
> get clean Markdown back — powered by Microsoft's
> [MarkItDown](https://github.com/microsoft/markitdown).

> [!NOTE]
> **🚧 Work in progress.** Markloom is under active development — features and
> APIs may still change and there's no tagged release yet. It's usable today;
> just expect churn. Feedback and issues are welcome. See the
> [roadmap](#roadmap) for what's next.

Drag a PDF, Word doc, PowerPoint, or spreadsheet into the dropzone; the service
converts it to Markdown in the background, keeps a history of your conversions,
and gives you a download link. Runs as a single Docker container.

<!-- TODO: add a screenshot / GIF here — see assets/ (light + dark, desktop + mobile) -->

## Features

- 📥 **Drag-and-drop** conversion of PDF, DOCX, PPTX, XLSX, and more
- ⚙️ **Background processing** with live status — big files don't block the UI
- 🕘 **Conversion history** stored in SQLite, with per-item delete
- ✨ **Optional "Enhanced" mode** — bring your own LLM to OCR text out of images
- 🧹 **Auto-expire** old files on a configurable retention window
- 🔒 **Optional login** (HTTP Basic) — off by default, one env var to enable
- 🐳 **One container**, one `docker compose up`

## Quick start

Save this as `compose.yaml`:

```yaml
services:
  markloom:
    image: ghcr.io/ttiimmaahh/markloom:latest
    ports:
      - "8674:8000"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

Then:

```bash
docker compose up -d
# open http://localhost:8674
```

That's it — no `.env`, no build, no account. Drag a file into the dropzone and
download the Markdown. Your history (SQLite db + converted Markdown) persists in
`./data` next to the compose file.

Want to tune retention, upload limits, auth, or the optional LLM? Every knob is
documented in the [full compose file](compose.yaml) and
[docs/configuration.md](docs/configuration.md).

> [!WARNING]
> The service ships with **no authentication** for convenience on a trusted LAN.
> **Do not expose it directly to the internet** without setting `AUTH_USERNAME`
> and `AUTH_PASSWORD` (see below) or placing an authenticating reverse proxy in
> front of it.

## Configuration

All configuration is via environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `/data` | Where the SQLite db and converted Markdown live |
| `RETENTION_DAYS` | `30` | Auto-delete conversions older than this. `0` = keep forever |
| `MAX_UPLOAD_MB` | `50` | Reject uploads larger than this |
| `ALLOWED_EXTENSIONS` | `pdf,docx,...` | File types the service accepts |
| `WORKER_THREADS` | `2` | Concurrent conversion threads |
| `MAX_ATTEMPTS` | `3` | Retries for a job interrupted by a restart before it's failed |
| `AUTH_USERNAME` | _(unset)_ | Set with `AUTH_PASSWORD` to require login |
| `AUTH_PASSWORD` | _(unset)_ | Set with `AUTH_USERNAME` to require login |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | _(unset)_ | Optional: a vision LLM (any OpenAI-compatible endpoint) that unlocks the per-file **Enhanced** OCR mode (see below) |

See [docs/configuration.md](docs/configuration.md) for enabling authentication,
the LLM option, and adding more file formats.

## Supported formats

Documents supported out of the box: **PDF, DOCX, PPTX, XLSX, XLS**, plus
text-like formats (HTML, CSV, JSON, XML, TXT, Markdown, EPUB) — defined by the
MarkItDown extras installed in [`backend/requirements.txt`](backend/requirements.txt).
To add more, add the extra to `requirements.txt` and the extension to
`ALLOWED_EXTENSIONS`.

**Audio** (`MP3, WAV, M4A, OGG, FLAC`) is transcribed to a timestamped Markdown
transcript by a **bundled local whisper** model — private, runs on CPU, no
external service and no LLM required. Optionally offload to a bring-your-own
OpenAI-compatible endpoint. See
[docs/configuration.md](docs/configuration.md#audio-transcription).

## Conversion quality — what to expect

Conversion is done by [MarkItDown](https://github.com/microsoft/markitdown), and
quality depends on how much **structure** the source format carries:

- **Office & HTML (DOCX, PPTX, XLSX, HTML) convert well** — they store real
  headings, tables, and lists that map cleanly to Markdown.
- **PDFs convert approximately.** PDF is a layout format with little semantic
  structure, so expect flattened tables, dropped images/logos, linearized
  columns, and **no OCR** (a scanned/image-only PDF yields little or nothing).
  This is a limitation of PDF extraction in general, not a bug in this tool.

> **Tip:** convert the earliest-format source you have — a DOCX converts far
> better than the PDF exported from it.

**Optional "Enhanced" mode:** configure a vision-capable LLM (`LLM_BASE_URL` /
`LLM_API_KEY` / `LLM_MODEL` — any OpenAI-compatible endpoint, including a local
Ollama/LM Studio/mlx-vlm server) and a per-file **Enhanced** toggle appears. It
OCRs text out of *images* embedded in documents — great for screenshot-heavy
PDFs — but it's much slower and may contain OCR errors, so it's opt-in per file
and never the default. It does **not** reconstruct born-digital PDF tables.

See [docs/conversion-quality.md](docs/conversion-quality.md) for a per-format
breakdown and Enhanced-mode trade-offs.

## Roadmap

Markloom is being actively built out. Planned next:

- 🗣️ **Speaker diarization** — label who's speaking in a transcript
  (`Speaker 1` / `Speaker 2`), opt-in on top of audio transcription
- 🔗 **URL & YouTube input** — convert a web page or a YouTube transcript, not
  just uploaded files
- 🗜️ **More inputs** — ZIP archives (convert everything inside into one document)
  plus `.msg` (Outlook) and `.ipynb`

Recently shipped: 🎙️ **audio transcription** (bundled local whisper, timestamped
transcripts), per-file **Enhanced** (LLM OCR) mode, conversion history with
delete, and in-place schema migrations.

## Development

```bash
cp .env.example .env
docker compose -f compose.dev.yaml up --build
```

This builds the image locally (React frontend → static assets served by
FastAPI) instead of pulling the published one.

To run the halves natively while iterating:

```bash
# backend (http://localhost:8000)
cd backend && pip install -r requirements-dev.txt && DATA_DIR=./data uvicorn app.main:app --reload
# frontend (http://localhost:5173, proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Checks:

```bash
cd backend  && pytest -q          # API tests (real end-to-end conversion)
cd frontend && npm run typecheck  # TypeScript
```

See [docs/project-structure.md](docs/project-structure.md) for how the pieces
fit together.

## Publishing (maintainers / forks)

Image publishing is **deliberate**: pushing a `v*` tag (or manually running the
[publish workflow](.github/workflows/publish.yml)) builds a multi-arch image and
pushes it to GHCR — no secrets to configure (it uses the built-in
`GITHUB_TOKEN`). Routine pushes to `main` only run CI; they don't publish.

> [!IMPORTANT]
> **One-time step:** GHCR packages are **private by default, even for a public
> repo.** After the first successful publish, open the package at
> `https://github.com/users/ttiimmaahh/packages/container/markloom/settings`,
> set **Visibility → Public**, and link it to this repo. Until you do, other
> people's `docker compose up` will fail with `denied / unauthorized`.

The quickstart pins `:latest`. For reproducible deploys, pin a version tag
instead (e.g. `ghcr.io/ttiimmaahh/markloom:1.0`).

## How it works

```
Browser (React + shadcn/ui + Tailwind)
   │  drop file → POST /api/convert (202 + job id)
   │  poll GET /api/jobs/{id} until done
   ▼
FastAPI  ──insert QUEUED──►  SQLite (jobs table)  ◄──sweep old rows── APScheduler
                                   │
                                   ▼ claim
                          ThreadPoolExecutor worker ──► MarkItDown ──► .md on disk
```

Everything coordinates through one `jobs` table: the API produces jobs, a
thread-pool worker consumes them (MarkItDown is synchronous, so it runs off the
async loop), and a scheduler purges expired ones.

## Attributions

- [MarkItDown](https://github.com/microsoft/markitdown) (MIT) — the conversion engine
- [FastAPI](https://fastapi.tiangolo.com/), [shadcn/ui](https://ui.shadcn.com/), [Tailwind CSS](https://tailwindcss.com/)
- Project structure & self-hosting ergonomics inspired by [mazanoke](https://github.com/civilblur/mazanoke)

## License

[MIT](LICENSE) © Tim Pearson
