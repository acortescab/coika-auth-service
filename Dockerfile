# syntax=docker/dockerfile:1

# Stages:
#   base       shared settings, no compiler
#   builder    compiler + uv, builds the production virtualenv
#   builder-dev  same, plus the dev group (pytest, ruff, ...)
#   dev        used by docker compose / CI (lint + tests run inside it)
#   runtime    LAST STAGE, so it is what `docker build .` produces and what ships to ECR

# ---- base ----
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Ensure logs are shown in real time (important for Docker logs)
ENV PYTHONUNBUFFERED=1

# The virtualenv lives outside /app so bind mounts cannot shadow it
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

# ---- builder ----
FROM base AS builder

ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# gcc is only here to build native extensions that lack a wheel (e.g. on arm64); it never reaches the final image
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Copy dependency metadata first to leverage Docker layer caching
COPY pyproject.toml uv.lock* ./

# Production dependencies only
RUN uv sync --frozen --no-dev --no-install-project

# ---- builder-dev ----
FROM builder AS builder-dev

RUN uv sync --frozen --group dev --no-install-project

# ---- dev (docker compose / CI) ----
# Runs as root on purpose: compose bind-mounts the checkout at /app and pytest/coverage write into it
# (.pytest_cache, coverage.xml); a fixed non-root uid cannot write there on Linux runners.
FROM base AS dev

COPY --from=builder-dev /opt/venv /opt/venv

COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Run migrations before starting the app
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- runtime (production image) ----
FROM base AS runtime

# Unprivileged user: a compromise of the app does not give root inside the container
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

# Only what is needed to run the app and its migrations (no tests, docs or tooling)
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./
COPY --chmod=755 entrypoint.sh /entrypoint.sh

USER app

EXPOSE 8000

# Run migrations before starting the app
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
