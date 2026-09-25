# syntax=docker/dockerfile:1.7
# Multi-stage build: dependencies are compiled once in `builder`, and the
# `runtime` image carries only the virtualenv + source (no compilers).

FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
# Non-root user: a compromised process must not own the container.
RUN groupadd -r app && useradd -r -g app -d /srv/app app \
    && mkdir -p /data/storage && chown -R app:app /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv/app
COPY --chown=app:app . .
USER app
EXPOSE 8000
# Production: no --reload, multiple workers. Compose overrides for dev.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
