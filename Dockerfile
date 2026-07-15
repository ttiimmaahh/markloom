# syntax=docker/dockerfile:1

# ---------- Stage 1: build the React frontend ----------
FROM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # emits /frontend/dist

# ---------- Stage 2: python runtime serving API + static assets ----------
FROM python:3.12-slim AS runtime

# curl: used by the compose healthcheck.
# Add MarkItDown native deps here if you enable extras that need them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./

# Built frontend assets — FastAPI serves these as static files.
COPY --from=frontend /frontend/dist ./static

ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
