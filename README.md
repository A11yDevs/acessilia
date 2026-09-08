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

Install the development dependencies and the extras used by CI:

```bash
poetry install --with dev --extras docling
```

Run the full suite from `tests/`:

```bash
poetry run pytest
```

GitHub Actions repeats this validation on Python 3.11 in both the slim and Docling installs for every pull request targeting `main`; the Docling variant also converts a real PDF. Failures, errors, and skipped tests are all rejected. See the [contribution guide](CONTRIBUTING.md) to set up the environment and learn the review flow.

## Docker

### Using the ready-made images

Once CI on `main` passes, GitHub Actions automatically publishes two Linux amd64 images to the GitHub Container Registry:

- `main`: includes Docling, RapidOCR, and PyTorch CPU for full structural analysis;
- `main-slim`: omits Docling, RapidOCR, and PyTorch for a smaller distribution.

```bash
docker pull ghcr.io/a11ydevs/acessilia:main
docker run --rm \
        --env-file .env \
        -p 8000:8000 \
        -p 8001:8001 \
        -v "$PWD/var:/app/var" \
        ghcr.io/a11ydevs/acessilia:main
```

Use `ghcr.io/a11ydevs/acessilia:main-slim` in the same command for the slim variant. To reproduce an exact version, use `sha-<commit>` or `sha-<commit>-slim`, as shown by the **Delivery** workflow run.

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

To build only the slim variant:

```bash
docker build -f infra/Dockerfile --build-arg WITH_DOCLING=false -t acessilia:slim .
```

### Docling and RapidOCR model cache

All model weights are downloaded at runtime on first Docling use (the distributed images embed no models), which makes that first conversion slower. Persist the `/app/var` volume so later runs reuse the same files, even offline.

- Hugging Face: `/app/var/cache/huggingface` (`HF_HOME`)
- RapidOCR: `/app/var/cache/rapidocr` (`RAPIDOCR_CACHE_DIR`)

Behavior:

- The first Docling run downloads (or copies) the weights into the volume.
- Subsequent runs restore them automatically before `RapidOCR` starts up.
- Deleting `./var` deletes the caches and forces a fresh download.

Example:

```bash
docker run --rm -e STRUCTURER=docling -v "$PWD/var:/app/var" \
        ghcr.io/a11ydevs/acessilia:main \
        python scripts/benchmark_pipelines.py tests/fixtures/tutorials/java-oo-3pgs.pdf \
        -o temp/output/regression-bench/java-oo-3pgs-offline/docling \
        --mode normal --export-formats txt,pdf,pdf_ua --pddl-extractor-backend docling
```

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Write tests for new functionality.
4. Run `poetry run pytest` and fix any failures, errors, or skipped tests.
5. Open a pull request.

Detailed rules live in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT © 2026 Jhonata Fernandes Cordeiro

## Changelog

Done:
- Created [docs/i18n.md](docs/i18n.md) and its Brazilian Portuguese translation [docs/i18n.pt-br.md](docs/i18n.pt-br.md) covering every internationalization feature the runtime supports (server-side locale negotiation, per-user locale detection for Telegram replies, canonical msgid pattern, locale-aware slash commands with Portuguese + English aliases, offered-locale list, localized logs/emails/web panel), where the i18n files and directories live, and step-by-step BASH recipes for adding a new internationalized string, internationalizing an already written code file, and adding/activating a new locale; moved the former Internationalization section of README.md out of both READMEs into these docs (leaving a summary + links), and linked the new pages into the [docs/README.md](docs/README.md) navigation tree.
- The two Portuguese-language docstrings in `backend/core/agno_support.py` (`build_agent` and the previously undocumented `require_workflow_classes`) plus the hardcoded Portuguese `RuntimeError` raised by `require_workflow_classes` when the optional Agno stack is absent now raise `RuntimeError(t(LOG_AGNO_NOT_INSTALLED))`, a new canonical msgid ("Agno is not installed. Run `poetry install` before using the workflow Executor." / pt_BR "Agno não está instalado. Execute `poetry install` antes de usar o workflow Executor.") added to `backend/log_messages.py` and registered in `scripts/gen_locale_catalogs.py` (import, `MESSAGES`, pt_BR translation) with both locale catalogs regenerated; both functions gained US-English docstrings with typed parameters and defaults per the code-quality rules (tests: `pytest`, 150 passed).
- Ported the sole remaining Portuguese docstring of `get_agno_model()` in `backend/ai/models/ai_client.py` to US English, adding a typed `Returns` annotation describing the provider selection (OpenRouter when `settings.ai_client == "openrouter"`, Ollama otherwise) per the code quality rules — no runtime output is affected, so no change to locale files or catalogs was needed (tests: `pytest`, 150 passed).
- Ported the Portuguese display strings and docstrings/comments in `frontend/agent_os.py` (the standalone AgentOS showcase server) to US English via canonical msgids: module docstring, the `_build_data_instructions` docstring plus its inline/fallback strings (now `t(WEB_AGENT_DATA_INSTRUCTIONS_FALLBACK)`), all inline comments, and the three hardcoded `description=` arguments (now `t(WEB_AGENT_OS_DESCRIPTION)`, `t(WEB_AGENT_VISION_DESCRIPTION)`, `t(WEB_AGENT_DATA_DESCRIPTION)`). The four new `WEB_AGENT_*` msgids were added to `frontend/web/messages.py` and registered in `scripts/gen_locale_catalogs.py` (imports, `MESSAGES`, pt_BR translations) with both locale catalogs regenerated; region-prompt keys `regiao_tabela`/`regiao_formula` are internal prompt filenames, not display text, so they were intentionally left as identifiers (tests: `pytest`, 150 passed).
- Internationalized every hardcoded Portuguese error/status string in the nominal-plan executor (`backend/core/execution/executor.py`): `MethodRegistry.register` empty-name error, all eight `_validate_binding` ValueError messages, the `_execute_step` start-job/execute-obligation/complete-job/unknown-action raises plus dry-run and no-handler/result-rejected messages, and all seven `_check_obligation_preconditions` ValueError messages. A new `backend/core/execution/messages.py` now holds the 23 canonical English `EXE_*` msgids (placeholders like `{method}`, `{unknown}`, `{plan_revision}` substituted by callers after lookup); each `raise` now goes through `t(EXE_*)`, the two PT docstrings (`MethodRegistry`/`ExecutorAgent`) and the `register`/`_validate_binding`/`_check_obligation_preconditions` methods gained US-English docstrings with typed params per the code-quality rules. All 23 msgids registered in `scripts/gen_locale_catalogs.py` (import, `MESSAGES`, pt_BR translations preserving the original Portuguese wording) and both locale catalogs regenerated. No test asserted on the old literals (verified by grep) so behavior is unchanged (tests: `pytest`, 150 passed).
- Added AGENTS.md and opencode.json.
