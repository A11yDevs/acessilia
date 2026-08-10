# syntax=docker/dockerfile:1.4
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH=/app

WORKDIR /app

RUN set -eux \
        && if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
                 sed -i '/^URIs: http:\/\/deb.debian.org\/debian$/s|http://deb.debian.org/debian|http://ftp.us.debian.org/debian|' /etc/apt/sources.list.d/debian.sources; \
             fi

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
                ca-certificates \
        curl \
                default-jre-headless \
        ffmpeg \
                fonts-dejavu \
        libgl1 \
        libglib2.0-0 \
        libmagic1 \
                pandoc \
        poppler-utils \
        tesseract-ocr \
            texlive-fonts-recommended \
                texlive-fonts-extra \
                texlive-latex-recommended \
            texlive-luatex \
                texlive-xetex \
                unzip \
                wget \
    && rm -rf /var/lib/apt/lists/*

ARG VERAPDF_VERSION=1.30.2
ARG VERAPDF_INSTALLER_REV=2
ENV VERAPDF_HOME=/opt/verapdf

RUN set -eux \
    && echo "verapdf-installer-rev=${VERAPDF_INSTALLER_REV}" \
    && wget -O /tmp/verapdf-installer.zip \
        "https://software.verapdf.org/releases/1.30/verapdf-greenfield-${VERAPDF_VERSION}-installer.zip" \
    && mkdir -p /tmp/verapdf-installer \
    && unzip -q /tmp/verapdf-installer.zip -d /tmp/verapdf-installer \
    && VERA_DIR="/tmp/verapdf-installer/verapdf-greenfield-${VERAPDF_VERSION}" \
    && printf '%s\n' \
        '<AutomatedInstallation langpack="eng">' \
        '    <com.izforge.izpack.panels.htmlhello.HTMLHelloPanel id="welcome"/>' \
        '    <com.izforge.izpack.panels.target.TargetPanel id="install_dir">' \
        '        <installpath>/opt/verapdf</installpath>' \
        '    </com.izforge.izpack.panels.target.TargetPanel>' \
        '    <com.izforge.izpack.panels.packs.PacksPanel id="sdk_pack_select">' \
        '        <pack index="0" name="veraPDF GUI" selected="true"/>' \
        '        <pack index="1" name="veraPDF CLI" selected="true"/>' \
        '    </com.izforge.izpack.panels.packs.PacksPanel>' \
        '    <com.izforge.izpack.panels.install.InstallPanel id="install"/>' \
        '    <com.izforge.izpack.panels.finish.FinishPanel id="finish"/>' \
        '</AutomatedInstallation>' \
        > /tmp/verapdf-installer/auto-install.xml \
    && chmod +x "${VERA_DIR}/verapdf-install" \
    && "${VERA_DIR}/verapdf-install" /tmp/verapdf-installer/auto-install.xml \
    && test -d /opt/verapdf \
    && ln -sf /opt/verapdf/verapdf /usr/local/bin/verapdf \
    && if [ ! -x /usr/local/bin/verapdf ]; then \
           CLI_PATH=$(find /opt/verapdf -maxdepth 2 -type f -name verapdf 2>/dev/null | head -n 1 || true); \
           if [ -n "${CLI_PATH}" ]; then ln -sf "${CLI_PATH}" /usr/local/bin/verapdf; fi; \
       fi \
    && test -x /usr/local/bin/verapdf \
    && rm -rf /tmp/verapdf-installer /tmp/verapdf-installer.zip

ARG POETRY_EXTRAS="docling"
ARG TORCH_VERSION=2.7.1
ARG TORCHVISION_VERSION=0.22.1

COPY pyproject.toml poetry.lock* ./

RUN pip install --upgrade pip \
    && pip install "poetry==$POETRY_VERSION" \
    && pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==${TORCH_VERSION}+cpu" \
        "torchvision==${TORCHVISION_VERSION}+cpu" \
    && if [ -n "$POETRY_EXTRAS" ]; then \
                 poetry export --only main --extras "$POETRY_EXTRAS" --without-hashes --format requirements.txt --output /tmp/requirements.txt; \
       else \
                 poetry export --only main --without-hashes --format requirements.txt --output /tmp/requirements.txt; \
             fi \
        && python - <<'PY'
from pathlib import Path

requirements_path = Path("/tmp/requirements.txt")
excluded = ("nvidia-", "torch==", "torchvision==", "triton==")
requirements = [
        line
        for line in requirements_path.read_text(encoding="utf-8").splitlines()
        if not line.lower().startswith(excluded)
]
requirements_path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
PY
RUN pip install --requirement /tmp/requirements.txt \
        && rm /tmp/requirements.txt

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
