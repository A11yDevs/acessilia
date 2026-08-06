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

RUN python - <<'PY'
from pathlib import Path
import tempfile

try:
    import rapidocr
    from rapidocr.utils.download_models import download_models
except ImportError:
    print("RapidOCR nao instalado; preload de modelos ignorado.")
    raise SystemExit(0)

root_dir = Path(rapidocr.__file__).resolve().parent
cfg_path = Path(tempfile.gettempdir()) / "rapidocr-preload.yaml"
cfg_path.write_text(
    f"""
Global:
    model_root_dir: {root_dir / 'models'}
    use_det: true
    use_cls: true
    use_rec: true

Det:
    engine_type: torch
    lang_type: ch
    model_type: small
    ocr_version: PP-OCRv6
    task_type: det

Cls:
    engine_type: torch
    lang_type: ch
    model_type: mobile
    ocr_version: PP-OCRv4
    task_type: cls

Rec:
    engine_type: torch
    lang_type: ch
    model_type: small
    ocr_version: PP-OCRv6
    task_type: rec
""".strip()
    + "\n",
    encoding="utf-8",
)
download_models(cfg_path)
print(f"RapidOCR models preloaded at {root_dir / 'models'}")
PY

COPY . .

EXPOSE 8000 8001

VOLUME /app/var
CMD ["python", "-m", "frontend.run"]

# --- Target de teste: inclui dependências de dev (pytest, respx) ---
FROM base AS test
RUN pip install pytest pytest-asyncio respx pytest-metadata pytest-html jsonschema
CMD ["pytest", "tests/", "-v"]
