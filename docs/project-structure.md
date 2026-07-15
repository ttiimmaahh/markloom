# Project structure

```
markloom/
├─ compose.yaml            # production: pulls the prebuilt GHCR image
├─ compose.dev.yaml        # development: builds the image locally
├─ Dockerfile             # multi-stage: node builds the SPA → python serves it
├─ .env.example           # every config knob, documented
├─ backend/
│  ├─ requirements.txt     # runtime deps (incl. markitdown extras)
│  ├─ requirements-dev.txt # + pytest/httpx for tests
│  ├─ pytest.ini
│  ├─ app/
│  │  ├─ config.py         # env-var settings (pydantic-settings)
│  │  ├─ db.py             # SQLite connection + schema (WAL mode)
│  │  ├─ jobs.py           # Job model + status state machine + queue ops
│  │  ├─ storage.py        # upload/markdown path conventions
│  │  ├─ converter.py      # thin MarkItDown wrapper (error mapping)
│  │  ├─ worker.py         # ThreadPoolExecutor background worker
│  │  ├─ cleanup.py        # APScheduler auto-expire sweep
│  │  ├─ auth.py           # optional env-gated HTTP Basic auth
│  │  └─ main.py           # FastAPI app: routes, middleware, static SPA
│  └─ tests/               # pytest API tests (real end-to-end conversion)
└─ frontend/
   ├─ src/
   │  ├─ components/        # Dropzone, JobHistory, StatusBadge, ThemeToggle, ui/*
   │  ├─ hooks/useJobs.ts   # loads history, polls while jobs are active
   │  ├─ lib/               # api client, cn(), formatters
   │  ├─ App.tsx
   │  └─ main.tsx
   └─ (Vite + Tailwind v4 + shadcn-style components)
```

## How the pieces coordinate

Everything talks through the single `jobs` table in SQLite:

- **`main.py`** (producer) validates an upload, saves the original, inserts a
  `queued` job, and nudges the worker.
- **`worker.py`** (consumer) atomically claims `queued → processing`, runs
  MarkItDown off the event loop, writes the `.md`, deletes the original
  (markdown-only retention), and marks the job `done` or `failed`.
- **`cleanup.py`** periodically deletes expired rows and their `.md` files.
- **`jobs.py`** owns the status state machine (`can_transition`) that every
  status change is validated against, plus crash recovery for jobs interrupted
  mid-conversion.

The React SPA polls `GET /api/jobs/{id}` until a job settles, then shows a
download link.
