# syntax=docker/dockerfile:1.4

# The image and CI install the same runtime versions from the committed lock
# (#405). uv is pinned by release tag and by digest: the tag names the version,
# the digest fixes the artifact that runs.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.17@sha256:03bdc89bb9798628846e60c3a9ad19006c8c3c724ccd2985a33145c039a0577b /uv /uvx /bin/

# Metadata and the two path dependencies first, so the dependency layer is
# reused when only application sources change. `--no-install-project` skips the
# application wheel but still installs docstruct and the SDK from the lock.
COPY pyproject.toml uv.lock .python-version README.md ./
COPY libs/docstruct ./libs/docstruct
COPY libs/sdk ./libs/sdk
COPY libs/core ./libs/core
RUN uv sync --locked --no-dev --no-editable --no-install-project

# The application, still installed from the lock and not editably. The final
# check proves docstruct and the SDK import from wheels, not from this tree.
COPY . .
RUN uv sync --locked --no-dev --no-editable \
    && /app/.venv/bin/python - <<'PY'
from pathlib import Path

import acessilia_sdk
import docstruct

for module in (docstruct, acessilia_sdk):
    location = Path(module.__file__).resolve()
    if "site-packages" not in location.parts:
        raise SystemExit(f"{module.__name__} is not installed from a wheel: {location}")
print("docstruct and the SDK are installed from wheels.")
PY

# The runtime carries the locked environment, not the builder's uv or cache.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app

RUN set -eux \
        && if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
                 sed -i '/^URIs: http:\/\/deb.debian.org\/debian$/s|http://deb.debian.org/debian|http://ftp.us.debian.org/debian|' /etc/apt/sources.list.d/debian.sources; \
             fi

# Operational tools (TeX Live, veraPDF, OCR, media inspection) run on the
# Toolbox, not here (docs/adr/0003), and so do the DOCX and PDF/UA exports.
# curl serves the compose healthcheck. Every Python dependency ships a
# linux/amd64 wheel, so no compiler is needed.
# APT_REFRESH (the CI passes the UTC date) changes this layer's cache key, so a
# build from the GitHub Actions cache still applies Debian security updates
# published since the layer was cached (#753).
ARG APT_REFRESH=
RUN echo "apt refresh: ${APT_REFRESH:-none}" \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        make \
    && rm -rf /var/lib/apt/lists/*

ARG GIT_COMMIT=
ARG IMAGE_TAG=
ARG IMAGE_DIGEST=

ENV GIT_COMMIT=${GIT_COMMIT} \
    IMAGE_TAG=${IMAGE_TAG} \
    IMAGE_DIGEST=${IMAGE_DIGEST}

# The base image keeps pip, setuptools and wheel in the system site-packages.
# Trivy scans them even though the application runs from /app/.venv; upgrading
# them replaces the vendored jars the scanner flags.
RUN /usr/local/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# The locked environment first; /app keeps the package data the wheel does not
# carry (templates, static assets, locale catalogs). PYTHONPATH above makes the
# application import from here while its dependencies come from the venv.
COPY --from=builder /app/.venv /app/.venv
COPY . .

EXPOSE 8000 8001

VOLUME /app/var
CMD ["python", "-m", "frontend.run"]
