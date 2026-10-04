# syntax=docker/dockerfile:1.7
# Render (Phase 26): API and worker in ONE container, for plans without a
# separate background worker or a shared disk. Build context: repository root.
#   docker build -f infrastructure/render/Dockerfile .
# Files go to S3-compatible storage (STORAGE_BACKEND=s3), since the container's
# disk is lost on every restart and deploy.
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install -r /tmp/backend-requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
# Tesseract OCR for scanned pages (as in the worker image).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r app && useradd -r -g app app && mkdir -p /data/storage && chown -R app:app /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv
COPY --chown=app:app backend/app /srv/app
COPY --chown=app:app backend/migrations /srv/migrations
COPY --chown=app:app backend/alembic.ini /srv/alembic.ini
COPY --chown=app:app workers/app /srv/worker
COPY --chown=app:app infrastructure/render/start.sh /srv/start.sh
USER app
EXPOSE 8000
CMD ["bash", "/srv/start.sh"]
