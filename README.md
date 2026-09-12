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

### Configuração de fórmulas matemáticas

O pipeline de acessibilização de fórmulas (PR #49) usa CodeFormula (~200M parâmetros, MIT) para extrair LaTeX de imagens. A referência de **~2 minutos por fórmula em CPU** é um relato histórico, não uma medição desta revisão nem uma garantia de latência.

| Variável | Default | Descrição |
|---|---|---|
| `DOCLING_FORMULA_ENRICHMENT` | `true` | Habilita extração de fórmulas via Docling |
| `FORMULA_IMAGE_CASCADE` | `true` | Habilita cascata OCR → CodeFormula para imagens |
| `FORMULA_CODEFORMULA_TIMEOUT` | `120` | Orçamento em segundos por recorte CodeFormula da cascata, incluindo preparação, startup, importação, carga do modelo e inferência |

Para desabilitar fórmulas ou ajustar o timeout, edite o `.env` sem mudar código:

```bash
DOCLING_FORMULA_ENRICHMENT=false  # desliga enriquecimento de página Docling
FORMULA_IMAGE_CASCADE=false      # desliga a cascata independente de recortes
FORMULA_CODEFORMULA_TIMEOUT=300  # orçamento de 5 minutos por recorte
```

A configuração é lida em cada chamada: aceita segundos numéricos positivos e
finitos, inclusive frações. Ausência usa `120`; valores inválidos, vazios, zero,
negativos, `nan` e infinitos geram aviso e usam `120`, sem falhar na importação.

Cada recorte usa um processo Python novo, sem shell nem reutilização do modelo
em memória do pai. O isolamento requer POSIX (Linux/macOS); em plataformas sem
grupos de processos, a cascata registra aviso e retorna fallback sem iniciar o modelo.
Ele herda a alocação e o ambiente existentes; não cria jobs
Slurm nem reserva outros recursos. O custo de iniciar o interpretador e carregar
o modelo novamente está dentro do orçamento, mesmo quando os pesos estão em cache.
Downloads necessários à carga também consomem esse tempo.

O orçamento começa antes da preparação dos temporários e da criação do processo;
o tempo já gasto é descontado da espera. Ao expirar, o grupo do processo recebe
`SIGKILL` e o filho direto é aguardado/recolhido antes do retorno. Essa limpeza
também ocorre em sucesso ou erro. A criação de processo e operações do sistema
operacional não são interrompíveis pelo timeout de Python: preparação, criação,
limpeza/recolhimento e leitura final podem acrescentar overhead ao tempo observado
da chamada. Não é uma garantia de retorno em exatamente N segundos sob falhas de SO.

Não há pipes de saída a drenar: stdout/stderr do reconhecedor são descartados;
um arquivo temporário separado recebe JSON limitado a 8192 bytes e LaTeX de até
2000 caracteres. O pai limita a leitura e rejeita resultado excessivo ou inválido.
Temporários são fechados em sucesso, timeout e erro. Falha, timeout, dependência
ausente ou resultado inválido retornam `''`, permitindo o fallback da cascata;
isso não declara a fórmula nem sua acessibilidade validadas.

Esse timeout aplica-se **somente ao CodeFormula da cascata de recortes**, em CPU
ou no acelerador escolhido pelo Docling. Não cobre o OCR anterior nem o
enriquecimento Docling de página/documento inteiro controlado por
`DOCLING_FORMULA_ENRICHMENT`.

Os testes de isolamento usam mocks e filhos Python locais, sem importar/carregar
Docling nos filhos de integração, sem rede, pesos ou inferência real. Os testes
de conversão real via latex2mathml ficam separados pela marca `docling`.
Esses testes não medem a latência de inferência real do CodeFormula.
A heurística OCR continua aproximada, não uma prova de classificação.

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
