# acessilia

[![CI](https://github.com/A11yDevs/acessilia/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/A11yDevs/acessilia/actions/workflows/ci.yml)
[![Delivery](https://github.com/A11yDevs/acessilia/actions/workflows/delivery.yml/badge.svg?branch=main)](https://github.com/A11yDevs/acessilia/actions/workflows/delivery.yml)

**acessilia** is an open-source project that extracts, classifies, and makes documents (PDF, DOCX, images, etc.) accessible using LLMs (Ollama, OpenRouter) and a modular pipeline.

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

## Architecture

The project follows the *Domain → Application → Interface* layering:

- **backend** – domain logic (agents, AI clients, pipeline, exporters) plus the **REST API** (the core).
- **frontend** – the API's clients: web panel, Telegram bot, and CLI.
- **tests** – unit test suite covering most modules.

### Standalone API

The **API** (`http://localhost:8000`) is the core: it receives files, enqueues them, processes them with LLMs, exports the accessible formats (TXT, DOCX, PDF, PDF/UA, HTML, MP3, ZIP), and makes downloads available via a token. All frontends (web, Telegram, CLI) consume it over HTTP using the shared client `frontend.clients.api_client.ApiClient`.

Main endpoints (`/api/v1`):

| Method | Route | Description |
|---|---|---|
| `POST` | `/jobs` | Submits a file to the queue (returns `task_id` and position) |
| `GET` | `/jobs/{task_id}` | Task status/progress |
| `POST` | `/jobs/{task_id}/cancel` | Cancels the task |
| `GET` | `/download/{token}` | Lists formats available for a token |
| `GET` | `/download/{token}/{format}` | Downloads the file (txt/docx/pdf/pdf_ua/html/mp3/zip) |
| `GET` | `/history?limit=20` | Conversion history |
| `GET` | `/stats` | Aggregated statistics |
| `GET` | `/health` | Server and AI model status |

> **Note:** the queue and task state live in memory inside the API; jobs are lost if the API restarts. Download tokens and the history persist in SQLite.

## Installation

### Using Poetry (recommended)

```bash
poetry install
cp .env.example .env   # configure the keys (AI, SMTP, Telegram)
```

## Running It

### Everything in one command (API + web + Telegram)

```bash
poetry run python -m frontend.run
# or: poetry run bot-acess
```

Starts the interfaces listed in `ENABLED_INTERFACES` (default: `api,telegram,web`):
- API on `http://localhost:8000`
- web panel on `http://localhost:8001`
- Telegram (requires `BOT_TOKEN`)

### Standalone API (for multi-process deploys)

```bash
poetry run python -m backend.api.run
```

Afterward, the web panel and Telegram point at `API_BASE_URL` (default `http://localhost:8000`).

### Web only or Telegram only

Edit `ENABLED_INTERFACES` in `.env`, e.g. `api,web`. The API must always be enabled (or running as another process) for the clients to work.

## Internationalization (i18n)

The project is internationalized in `en_US` (default) and `pt_BR` using **Babel** (`babel` in `pyproject.toml`). User-facing strings, Telegram bot command responses, e-mails, and server-side log lines are variablized through per-locale strings files (`backend/locales/<locale>/LC_MESSAGES/messages.po`), and the runtime-selected locale decides which strings file is used for variable substitution — adding a new supported locale requires only one new strings file (minimal code changes).

- The active server locale is negotiated from `LOCALE`/`LANGUAGE` in the environment against the supported locales, falling back to `en_US`; the Telegram bot additionally detects each user's language and replies in the user's own locale when it is offered by `I18N_LOCALES_ACTIVE` in `.env` (bottom section: `LOCALE`, `I18N_LOCALES_ACTIVE`).
- Code looks up strings through `t()` in [backend/i18n.py](backend/i18n.py) using canonical English message ids defined as `MSG_*`/`LOG_*`/`EXE_*` constants; if a translation is missing for the active locale, Babel falls back to the English msgid unchanged.
- Portuguese slash commands (`/ativar`, `/ajuda`, ...) keep working in every locale, each with a US English alias (`/activate`, `/help`, ...) — command listings and responses render in the user's locale.

Full documentation — where the i18n files live, how to add a new string, how to internationalize an existing file, and how to add and activate a new locale — is in [docs/i18n.md](docs/i18n.md). (Brazilian Portuguese: [documentação em pt-BR](docs/i18n.pt-br.md))

## Tests

Install the development dependencies used by CI:

```bash
poetry install --with dev
```

Run the full suite from `tests/`:

```bash
poetry run pytest -m "not e2e"
```

GitHub Actions runs this suite on Python 3.11 for pull requests targeting `main`, `develop` and `release/**`. Failures, errors and unexpected skips are rejected. The `e2e` tests require a live Toolbox and run separately. See the [contribution guide](CONTRIBUTING.md).

## Interactive Notebooks

The [`docs/notebooks/`](docs/notebooks/) directory contains Jupyter notebooks that demonstrate and diagnose the pipeline interactively:

- **[PDDL Pipeline Diagnostic](docs/notebooks/diagnose_pipeline_pddl.ipynb)** — walks through each stage of the PDDL pipeline (dataset retrieval via Toolbox, structure extraction, manifest building, visual detection, image enrichment, text rendering, and cache inspection). The notebook fetches sample images from the `acessilia-dataset` through the Toolbox dataset API — no hardcoded local paths required.

To run the notebooks:

```bash
poetry install --with dev
poetry run jupyter notebook docs/notebooks/
```

Or open them directly in VS Code and execute cells with the built-in notebook support.

## Docker

### Using the ready-made images

After CI passes on `main`, `develop` or `release/**`, Delivery validates and publishes one Linux amd64 image. Docling/RapidOCR run remotely in Toolbox; they are not dependencies of the application image.

```bash
docker pull ghcr.io/a11ydevs/acessilia:main
docker run --rm \
        --env-file .env \
        -p 8000:8000 \
        -p 8001:8001 \
        -v "$PWD/var:/app/var" \
        ghcr.io/a11ydevs/acessilia:main
```

To reproduce an exact version, use `sha-<7-character-commit>` or the digest shown by the **Delivery** workflow.

For a producion server that updates main automatically use:

```bash
./scripts/setup-producao.sh
```

The complete promotion, validation, and rollback procedure is in [docs/producao-systemd.md](docs/producao-systemd.md).

### Building locally

```bash
docker compose up -d --build
```

The container exposes `8000` (API) and `8001` (web), persists everything under `./var`, and runs its health check at `/api/v1/health`.

### Remote structural extraction

Use `STRUCTURER=toolbox`, `PIPELINE_ENGINE=pddl` and `TOOLBOX_PROVIDER=docling`. Set `TOOLBOX_BASE_URL` to a reachable instance; inside Docker, `http://host.docker.internal:8002` reaches Toolbox on the host. Provider models and model caches belong to Toolbox. The application's `/app/var` volume stores data, temporary files and logs.

```bash
poetry run python -m scripts.check_toolbox
poetry run python -m scripts.manifest tests/fixtures/tutorials/java-oo-3pgs.pdf
```

The first command checks health/capabilities; the second extracts and validates a manifest through the API. PDDL generation is deterministic. Vision/Data can enrich images and tables before planning. Plan validation is an optional dry run.

### Standalone formula utilities

The retained local formula helper uses `FORMULA_CODEFORMULA_TIMEOUT` (default: 120 positive, finite seconds) for isolated CodeFormula recognition. Invalid values warn and fall back to 120; fractional seconds are accepted. This budget covers crop preparation, interpreter/model startup and inference, including any downloads. OS process creation/cleanup and output reading can add overhead. The helper requires POSIX process groups and a separately installed local model stack; without these it returns the empty-string fallback.

Recognition runs in a fresh child process and kills/reaps its process group on timeout. Temporary JSON output is limited to 8192 bytes and LaTeX to 2000 characters; malformed or oversized results also fall back. The budget does not cover the preceding OCR. These utilities are separate from the current PDDL flow; their local-child tests do not measure real model inference. The former `DOCLING_FORMULA_ENRICHMENT` and `FORMULA_IMAGE_CASCADE` application switches have no current consumers.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Write tests for new functionality.
4. Run `poetry run pytest` and fix any failures, errors, or skipped tests.
5. Open a pull request.

Detailed rules live in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT © 2026 Jhonata Fernandes Cordeiro
