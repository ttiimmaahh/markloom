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
│  │  ├─ conversion_subprocess.py # killable Enhanced conversion entry point
│  │  ├─ worker.py         # threads + Enhanced child-process supervision
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
  Standard/audio work in threads, and supervises Enhanced work in a killable
  child process. It writes the `.md`, deletes the original (markdown-only
  retention), and marks the job `done`, `failed`, or `canceled`.
- **`cleanup.py`** periodically deletes expired terminal rows and their `.md`
  files without removing active work.
- **`jobs.py`** owns atomic status transitions, cancellation eligibility, and
  crash recovery for jobs interrupted mid-conversion.

The React SPA polls `GET /api/jobs/{id}` until a job settles, then shows a
download link. Cancelable rows expose `POST /api/jobs/{id}/cancel` through a
Stop action.
