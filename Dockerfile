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

# Run as a non-root user so a compromised document parser doesn't get root in
# the container. /data is pre-created with matching ownership so a fresh named
# volume inherits it; a host bind-mount keeps the host directory's owner — chown
# it to uid 1000 (see docs/configuration.md#file-permissions).
RUN useradd --uid 1000 --user-group --create-home markloom \
    && mkdir -p /data \
    && chown markloom:markloom /data
USER markloom

# Release version, injected by publish.yml from the git tag. Local builds show "dev".
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
