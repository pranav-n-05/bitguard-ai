# syntax=docker/dockerfile:1
# Single-image build for Render: React console + FastAPI + Celery worker in one service
# (one service so the API and worker share the persistent disk: uploads, reports, model artifacts).

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS wheels
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BITGUARD_STATIC_DIR=/app/static
RUN useradd --create-home --uid 10001 bitguard && mkdir -p /data/storage /data/models
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
WORKDIR /app
COPY backend/ /app/
COPY --from=web /web/dist /app/static
COPY infrastructure/docker/render-entrypoint.sh infrastructure/docker/render-run.sh /app/
RUN chmod +x /app/render-entrypoint.sh /app/render-run.sh
# Starts as root only to fix ownership of the mounted disk, then drops to the unprivileged user.
ENTRYPOINT ["/app/render-entrypoint.sh"]
