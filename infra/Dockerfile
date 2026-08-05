# syntax=docker/dockerfile:1.4
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libmagic1 \
        poppler-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

ARG POETRY_EXTRAS=""

COPY pyproject.toml poetry.lock* ./

RUN pip install --upgrade pip \
    && pip install "poetry==$POETRY_VERSION" \
    && poetry config virtualenvs.create false \
    && if [ -n "$POETRY_EXTRAS" ]; then \
         poetry install --only main --extras "$POETRY_EXTRAS" --no-root --no-interaction --no-ansi; \
       else \
         poetry install --only main --no-root --no-interaction --no-ansi; \
       fi

COPY . .

EXPOSE 8000 8001

VOLUME /app/var
CMD ["python", "-m", "frontend.run"]

# --- Target de teste: inclui dependências de dev (pytest, respx) ---
FROM base AS test
RUN poetry install --with dev --no-root --no-interaction --no-ansi
CMD ["poetry", "run", "pytest", "tests/", "-v"]
