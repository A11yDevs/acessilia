# Docker Compose — Running Acessilia

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](docker-compose.pt-br.md)

This document describes how to run Acessilia locally using Docker, both with a
**build from source** and with **pre-published images on GHCR**
(without needing to download the repository or compile anything).

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with integrated Compose V2)
- Internet access to download images or dependencies

---

## 1. Running with a local build (from source)

Uses the default `docker-compose.yml`, which builds the image locally.

```bash
# 1. Clone the repository (if you don't already have it)
git clone git@github.com:A11yDevs/acessilia.git
cd acessilia

# 2. Configure the environment
cp .env.example .env
# Edit .env with your credentials (at least BOT_TOKEN if you'll use Telegram)

# 3. Start the container (automatic build)
docker compose up -d
```

This builds the image from `infra/Dockerfile` with the **docling** variant
(full, ~4-6 GB). The container exposes:

| Port | Service  |
|------|----------|
| 8000 | REST API |
| 8001 | Web panel |

### Slim variant (without Docling)

For a smaller image (~2 GB) without Docling OCR:

```bash
docker compose build --build-arg WITH_DOCLING=false
docker compose up -d
```

---

## 2. Running with a GHCR image (no build)

Uses the `docker-compose.staging.yml`, which already references the images
published on the GitHub Container Registry. **It does not require the source code.**

```bash
# 1. Create a directory for the environment
mkdir acessilia-staging && cd acessilia-staging

# 2. Download only the compose file and .env.example
curl -O https://raw.githubusercontent.com/A11yDevs/acessilia/develop/docker-compose.staging.yml
curl -O https://raw.githubusercontent.com/A11yDevs/acessilia/develop/.env.example

# 3. Configure the environment
cp .env.example .env
# Edit .env with your credentials

# 4. Create the data directories
mkdir -p var/temp var/data var/logs

# 5. Start the container (downloads the image automatically)
docker compose -f docker-compose.staging.yml up -d
```

This downloads and runs `ghcr.io/a11ydevs/acessilia:develop` (docling variant).

### Using the slim variant

Edit the `docker-compose.staging.yml` and change the image tag:

```yaml
image: ghcr.io/a11ydevs/acessilia:develop-slim
```

Or via sed (macOS):

```bash
sed -i '' 's/:develop$/:develop-slim/' docker-compose.staging.yml
docker compose -f docker-compose.staging.yml up -d
```

On Linux use `sed -i 's/:develop$/:develop-slim/'` (no `''`).

---

## 3. Tags available on GHCR

CI/CD automatically publishes the following images:

| Tag                              | Variant | Description                           |
|----------------------------------|---------|---------------------------------------|
| `:develop`                       | docling | Latest build of the `develop` branch  |
| `:develop-slim`                  | slim    | Latest build of `develop` (light)     |
| `:main`                          | docling | Latest build of the `main` branch     |
| `:main-slim`                     | slim    | Latest build of `main` (light)        |
| `:latest`                        | docling | Points to `main`                      |
| `:latest-slim`                   | slim    | Points to `main` (light)              |
| `:sha-<7-char-commit>`           | docling | Build of a specific commit            |
| `:sha-<7-char-commit>-slim`      | slim    | Build of a specific commit (light)    |
| `:X.Y.Z`                         | docling | Versioned release                     |
| `:X.Y.Z-slim`                    | slim    | Versioned release (light)             |
| `:X.Y` / `:X`                    | docling | Semantic alias of the release         |
| `:X.Y-slim` / `:X-slim`          | slim    | Semantic alias of the release (light) |

Example to pull an image manually:

```bash
docker pull ghcr.io/a11ydevs/acessilia:develop
docker pull ghcr.io/a11ydevs/acessilia:sha-abc1234
```

---

## 4. Configuring `.env`

The minimum needed to test:

```env
# Active interfaces
ENABLED_INTERFACES=api,web

# API
API_HOST=0.0.0.0
API_PORT=8000
API_BASE_URL=http://localhost:8000
WEB_PORT=8001

# Directories
TEMP_DIR=var/temp
DATA_DIR=var/data
LOGS_DIR=var/logs

# Logging
LOG_LEVEL=INFO

# AI Client (pick one)
AI_CLIENT=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1/chat/completions
OLLAMA_MODEL=llama3.2-vision

# Document structuring
STRUCTURER=docling   # or pymupdf (lighter, no extra dependencies)

# Pipeline
PIPELINE_ENGINE=legacy
```

> **Ollama local tip:** Use `host.docker.internal` instead of `localhost`
> so the container can reach the Ollama server running on the host.

---

## 5. Useful commands

```bash
# Watch logs in real time
docker compose logs -f

# Stop and remove the container
docker compose down

# Run a command interactively inside the container
docker compose exec acessilia python -c "from backend.core.version import __version__; print(__version__)"

# Check the API health endpoint
curl http://localhost:8000/api/v1/health

# Inspect which image is running
docker inspect acessilia-instance --format '{{.Config.Image}}'

# Manually pull a specific image
docker pull ghcr.io/a11ydevs/acessilia:sha-abc1234
```

---

## 6. Automatic updates (staging and production)

If you are running a staging server, you can configure **automatic updates**
via a systemd timer. The script consults the **GitHub API** every
**5 minutes** and only runs `docker pull` when there is a new commit on `develop`.

```bash
# Full setup (recommended)
./scripts/setup-homologacao.sh

# Or do it manually
# See docs/homologacao-systemd.md for manual instructions
```

For production, use [docs/producao-systemd.md](docs/producao-systemd.md) or run
`./scripts/setup-producao.sh`. The environment tracks `main` by default using
`docker-compose.production.yml` and `scripts/production-update.sh`.

**Requires:** `jq` and a GitHub token with the `read:packages` scope.

---

## 7. Image variants

| Variant   | Approx. size | Docling | OCR | Recommended use                |
|-----------|--------------|---------|-----|--------------------------------|
| **docling** | ~4-6 GB    | ✅ Yes | ✅ Native (CPU) | Maximum document precision |
| **slim**   | ~2 GB      | ❌ No  | ❌ Fallback pymupdf | Fast tests, limited resources |

The **docling** variant is the default and offers:
- Table, figure, and formula detection
- Native CPU-only OCR (no GPU)
- More precise structural extraction

The **slim** variant automatically falls back to `pymupdf` with a warning in the log.

---

## 8. Troubleshooting

### Container won't start — port in use

```bash
# Check whether the port is already in use
lsof -i :8000
# Change the ports in docker-compose.yml or stop the conflicting service
```

### Health check failing

```bash
# Check the logs
docker compose logs acessilia
# Confirm that .env has ENABLED_INTERFACES=api (minimum for the health check)
```

### Ollama not reachable from the container

Make sure that:
1. Ollama is running on the host
2. The `OLLAMA_BASE_URL` variable uses `http://host.docker.internal:11434/...`
3. On Linux, use `--network host` or the gateway IP: `http://172.17.0.1:11434/...`

### Image not found on GHCR

```bash
# Check whether the tag exists
docker pull ghcr.io/a11ydevs/acessilia:develop
# If it fails, log in to GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u <your-user> --password-stdin
```
