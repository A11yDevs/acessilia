# acessilia

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

```bash
poetry run pytest
```

## Docker

```bash
docker compose up -d --build
```

O container expõe `8000` (API) e `8001` (web), persiste tudo em `./var` e roda o healthcheck em `/api/v1/health`.

### Cache offline do RapidOCR

Quando o fluxo com `Docling` é usado pela primeira vez, o `RapidOCR` pode baixar pesos de OCR em tempo de execução. Para evitar downloads recorrentes em benchmarks e execuções seguintes, o projeto agora persiste esses arquivos em um cache local.

- Variável de ambiente: `RAPIDOCR_CACHE_DIR`
- Valor padrão: `var/cache/rapidocr`

Comportamento:

- Na primeira execução com Docling, os pesos são baixados e copiados para o cache local.
- Nas execuções seguintes, os arquivos são restaurados automaticamente antes de inicializar o `RapidOCR`.

Exemplo:

```bash
export RAPIDOCR_CACHE_DIR=var/cache/rapidocr
docker run --rm -e STRUCTURER=docling -v "$PWD:/app" -w /app acessilia:test-docling \
	python scripts/benchmark_pipelines.py tests/fixtures/tutorials/java-oo-3pgs.pdf \
	-o temp/output/regression-bench/java-oo-3pgs-offline/docling \
	--mode normal --export-formats txt,pdf,pdf_ua --pddl-extractor-backend docling
```

Se quiser embutir os modelos já na imagem Docker, o `infra/Dockerfile` também inclui um passo de preload no build quando a imagem é reconstruída com acesso à rede.

## Contribuindo

1. Fork o repositório.
2. Crie uma branch de feature.
3. Escreva testes para a nova funcionalidade.
4. Rode `pytest` – garanta que a cobertura permaneça alta.
5. Envie um pull request.

## Licença

MIT © 2026 Jhonata Fernandes Cordeiro
