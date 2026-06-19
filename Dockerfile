FROM node:22-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS python-deps

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY upvote_monitor/ ./upvote_monitor/
COPY main.py ./main.py

RUN uv sync --frozen --no-dev

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg curl libicu-dev xxd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=python-deps /app /app
COPY --from=frontend-build /app/frontend/build ./frontend/build

RUN mkdir -p /data /download

EXPOSE 3134

CMD ["uv", "run", "uvicorn", "upvote_monitor.app:app", "--host", "0.0.0.0", "--port", "3134"]
