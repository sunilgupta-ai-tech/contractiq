# syntax=docker/dockerfile:1.7
# Build context: repository root (the worker reuses backend domain code).
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
# Tesseract OCR engine + English language data, used for scanned pages.
# Add more languages as packages (e.g. tesseract-ocr-deu) and list them in
# OCR_LANGUAGES ("eng+deu"). Poppler is not needed: PyMuPDF renders pages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r app && useradd -r -g app app && mkdir -p /data/storage && chown -R app:app /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv
# Shared domain package `app` (backend) + worker package `worker`.
COPY --chown=app:app backend/app /srv/app
COPY --chown=app:app workers/app /srv/worker
USER app
CMD ["arq", "worker.main.WorkerSettings"]
