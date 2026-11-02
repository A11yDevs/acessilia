# syntax=docker/dockerfile:1.4
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
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
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

ARG GIT_COMMIT=
ARG IMAGE_TAG=
ARG IMAGE_DIGEST=

ENV GIT_COMMIT=${GIT_COMMIT} \
    IMAGE_TAG=${IMAGE_TAG} \
    IMAGE_DIGEST=${IMAGE_DIGEST}

COPY pyproject.toml ./
COPY libs/docstruct ./libs/docstruct
COPY libs/sdk ./libs/sdk

RUN pip install --upgrade pip \
    && pip install ./libs/docstruct --no-cache-dir \
    && pip install ./libs/sdk --no-cache-dir \
    && pip install . --no-cache-dir

COPY . .

EXPOSE 8000 8001

VOLUME /app/var
CMD ["python", "-m", "frontend.run"]
