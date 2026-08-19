# acessilia

[![CI](https://github.com/A11yDevs/acessilia/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/A11yDevs/acessilia/actions/workflows/ci.yml)
[![Delivery](https://github.com/A11yDevs/acessilia/actions/workflows/delivery.yml/badge.svg?branch=main)](https://github.com/A11yDevs/acessilia/actions/workflows/delivery.yml)

**acessilia** é um projeto de código‑aberto que extrai, classifica e torna documentos (PDF, DOCX, imagens, etc.) acessíveis usando LLMs (Ollama, OpenRouter) e um pipeline modular.

## Arquitetura

O projeto segue a camada *Domínio → Aplicação → Interface*:

- **backend** – lógica de domínio (agentes, clientes de IA, pipeline, exportadores) e a **API REST** (núcleo).
- **frontend** – clientes da API: painel web, bot do Telegram e CLI.
- **tests** – suíte de testes unitários cobrindo a maioria dos módulos.

### API standalone

A **API** (`http://localhost:8000`) é o núcleo: recebe o arquivo, coloca na fila, processa com o LLM, exporta os formatos acessíveis (TXT, DOCX, PDF, PDF/UA, HTML, MP3, ZIP) e disponibiliza o download via token. Os frontends (web, Telegram, CLI) consomem tudo por HTTP usando o cliente compartilhado `frontend.clients.api_client.ApiClient`.

Principais endpoints (`/api/v1`):

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/jobs` | Envia arquivo para a fila (retorna `task_id` e posição) |
| `GET` | `/jobs/{task_id}` | Status/progresso da tarefa |
| `POST` | `/jobs/{task_id}/cancel` | Cancela a tarefa |
| `GET` | `/download/{token}` | Lista formatos disponíveis de um token |
| `GET` | `/download/{token}/{format}` | Baixa o arquivo (txt/docx/pdf/pdf_ua/html/mp3/zip) |
| `GET` | `/history?limit=20` | Histórico de conversões |
| `GET` | `/stats` | Estatísticas agregadas |
| `GET` | `/health` | Status do servidor e do modelo de IA |

> **Nota:** a fila e o estado das tarefas vivem em memória na API; jobs são perdidos se a API reiniciar. Tokens de download e histórico persistem em SQLite.

## Instalação

### Usando Poetry (recomendado)

```bash
poetry install
cp .env.example .env   # configure as chaves (AI, SMTP, Telegram)
```

## Execução

### Tudo em um comando (API + web + Telegram)

```bash
poetry run python -m frontend.run
# ou: poetry run bot-acess
```

Inicia as interfaces listadas em `ENABLED_INTERFACES` (default: `api,telegram,web`):
- API em `http://localhost:8000`
- Painel web em `http://localhost:8001`
- Telegram (requer `BOT_TOKEN`)

### API isolada (para deploy de múltiplos processos)

```bash
poetry run python -m backend.api.run
```

Depois, o painel web e o Telegram apontam para `API_BASE_URL` (default `http://localhost:8000`).

### Somente web ou somente Telegram

Edite `ENABLED_INTERFACES` em `.env`, ex.: `api,web`. A API deve sempre estar habilitada (ou rodando em outro processo) para os clientes funcionarem.

## Testes

Instale as dependências de desenvolvimento e os extras usados pelo CI:

```bash
poetry install --with dev --extras "docling observability"
```

Execute a suíte completa da pasta `tests/`:

```bash
poetry run pytest
```

Testes de carga ficam em [observability/](observability/), junto do resto da parte de medição.

O GitHub Actions repete essa validação em Python 3.11 nas instalações slim e Docling para todo pull request direcionado à `main`. A variante Docling também converte um PDF real. Falhas, erros e testes pulados são rejeitados. Consulte o [guia de contribuição](CONTRIBUTING.md) para preparar o ambiente e entender o fluxo de revisão.

## Docker

### Usando a imagem pronta

Depois que o CI da `main` passa, o GitHub Actions publica automaticamente duas imagens Linux amd64 no GitHub Container Registry:

- `main`: inclui Docling, RapidOCR e PyTorch CPU para análise estrutural completa;
- `main-slim`: omite Docling, RapidOCR e PyTorch para uma distribuição menor.

```bash
docker pull ghcr.io/a11ydevs/acessilia:main
docker run --rm \
	--env-file .env \
	-p 8000:8000 \
	-p 8001:8001 \
	-v "$PWD/var:/app/var" \
	ghcr.io/a11ydevs/acessilia:main
```

Use `ghcr.io/a11ydevs/acessilia:main-slim` no mesmo comando para a variante slim. Para reproduzir uma versão exata, use `sha-<commit>` ou `sha-<commit>-slim`, mostradas na execução do workflow **Delivery**.

### Construindo localmente

```bash
docker compose up -d --build
```

O container expõe `8000` (API) e `8001` (web), persiste tudo em `./var` e roda o healthcheck em `/api/v1/health`.

## Observabilidade

Desligada por padrão. Para usar a stack local, ajuste `OBSERVABILITY_ENABLED=true` no `.env` e suba Prometheus, Grafana, Loki, Alloy, Langfuse e o painel próprio:

```bash
docker compose --profile monitoring up -d
```

O Grafana abre em http://localhost:3000 já com o dashboard pronto. Como ligar na aplicação e onde cada número aparece: [observability/README.md](observability/README.md).

Para construir somente a variante slim:

```bash
docker build -f infra/Dockerfile --build-arg WITH_DOCLING=false -t acessilia:slim .
```

### Cache de modelos Docling e RapidOCR

Nenhum modelo é embutido nas imagens distribuídas. No primeiro processamento com Docling, os modelos são baixados em tempo de execução; por isso essa primeira conversão é mais lenta. O volume `/app/var` deve ser persistido para que execuções seguintes funcionem com os mesmos arquivos, inclusive sem rede.

- Hugging Face: `/app/var/cache/huggingface` (`HF_HOME`)
- RapidOCR: `/app/var/cache/rapidocr` (`RAPIDOCR_CACHE_DIR`)

Comportamento:

- Na primeira execução com Docling, os pesos são baixados para o volume ou copiados para ele.
- Nas execuções seguintes, os arquivos são restaurados automaticamente antes de inicializar o `RapidOCR`.
- Remover `./var` remove os caches e força um novo download.

Exemplo:

```bash
docker run --rm -e STRUCTURER=docling -v "$PWD/var:/app/var" \
	ghcr.io/a11ydevs/acessilia:main \
	python scripts/benchmark_pipelines.py tests/fixtures/tutorials/java-oo-3pgs.pdf \
	-o temp/output/regression-bench/java-oo-3pgs-offline/docling \
	--mode normal --export-formats txt,pdf,pdf_ua --pddl-extractor-backend docling
```

## Contribuindo

1. Fork o repositório.
2. Crie uma branch de feature.
3. Escreva testes para a nova funcionalidade.
4. Rode `poetry run pytest` e corrija falhas, erros ou skips.
5. Envie um pull request.

As regras detalhadas estão em [CONTRIBUTING.md](CONTRIBUTING.md).

## Licença

MIT © 2026 Jhonata Fernandes Cordeiro
