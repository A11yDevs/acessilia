# acessilia

[![CI](https://github.com/A11yDevs/acessilia/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/A11yDevs/acessilia/actions/workflows/ci.yml)
[![Delivery](https://github.com/A11yDevs/acessilia/actions/workflows/delivery.yml/badge.svg?branch=main)](https://github.com/A11yDevs/acessilia/actions/workflows/delivery.yml)

**acessilia** é um projeto de código-aberto que extrai, classifica e torna documentos (PDF, DOCX, imagens, etc.) acessíveis usando LLMs (Ollama, OpenRouter) e um pipeline modular.

Leia esta documentação também em [inglês](README.md).

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
cp .env.example .env   # configure as chaves (IA, SMTP, Telegram)
```

## Execução

### Tudo em um comando (API + web + Telegram)

```bash
poetry run python -m frontend.run
# ou: poetry run bot-acess
```

Inicia as interfaces listadas em `ENABLED_INTERFACES` (padrão: `api,telegram,web`):
- API em `http://localhost:8000`
- Painel web em `http://localhost:8001`
- Telegram (requer `BOT_TOKEN`)

### API isolada (para deploy de múltiplos processos)

```bash
poetry run python -m backend.api.run
```

Depois, o painel web e o Telegram apontam para `API_BASE_URL` (padrão `http://localhost:8000`).

### Somente web ou somente Telegram

Edite `ENABLED_INTERFACES` em `.env`, ex.: `api,web`. A API deve sempre estar habilitada (ou rodando em outro processo) para os clientes funcionarem.

## Internacionalização (i18n)

O projeto é internacionalizado em `en_US` (padrão) e `pt_BR` usando **Babel** (`babel` no `pyproject.toml`). Os textos visíveis ao usuário, as respostas aos comandos do bot do Telegram, os e-mails e as linhas de log do servidor são variabilizados por meio de arquivos de strings por locale (`backend/locales/<locale>/LC_MESSAGES/messages.po`), e o locale escolhido em runtime decide qual arquivo de strings é usado para a substituição de variáveis — adicionar um novo locale suportado exige apenas um novo arquivo de strings (mudanças mínimas de código).

- O locale do servidor ativo é negociado a partir de `LOCALE`/`LANGUAGE` no ambiente contra os locales suportados, caindo no padrão `en_US`; o bot do Telegram ainda detecta o idioma de cada usuário e responde no próprio locale do usuário quando ele é oferecido por `I18N_LOCALES_ACTIVE` no `.env` (seção no rodapé: `LOCALE`, `I18N_LOCALES_ACTIVE`).
- O código busca as strings por meio de `t()` em [backend/i18n.py](backend/i18n.py) usando ids de mensagens canônicos em inglês definidos como constantes `MSG_*`/`LOG_*`/`EXE_*`; se uma tradução estiver ausente para o locale ativo, o Babel recorre ao msgid original em inglês sem modificação.
- Os comandos portugueses (`/ativar`, `/ajuda`, ...) continuam funcionando em qualquer locale, cada um com um alias em inglês (`/activate`, `/help`, ...) — as listagens de comandos e as respostas são renderizadas no locale do usuário.

A documentação completa — onde ficam os arquivos de i18n, como adicionar uma nova string, como internacionalizar um arquivo já escrito e como adicionar e ativar um novo locale — está em [docs/i18n.md](docs/i18n.md). (Inglês: [documentation in English](docs/i18n.md))

## Testes

Instale as dependências de desenvolvimento usadas pelo CI:

```bash
poetry install --with dev
```

Execute a suíte completa da pasta `tests/`:

```bash
poetry run pytest -m "not e2e"
```

O GitHub Actions executa a suíte em Python 3.11 para PRs direcionados a `main`, `develop` e `release/**`. Falhas, erros e skips inesperados são rejeitados. Os testes `e2e` exigem uma Toolbox real e são executados separadamente. Consulte o [guia de contribuição](CONTRIBUTING.md).

## Notebooks Interativos

O diretório [`docs/notebooks/`](docs/notebooks/) contém notebooks Jupyter que demonstram e diagnosticam o pipeline de forma interativa:

- **[Diagnóstico do Pipeline PDDL](docs/notebooks/diagnose_pipeline_pddl.ipynb)** — percorre cada etapa do pipeline PDDL (obtenção de dataset via Toolbox, extração de estrutura, construção do manifesto, detecção visual, enriquecimento de imagens, renderização de texto e inspeção de cache). O notebook busca imagens de exemplo do `acessilia-dataset` através da API de datasets da Toolbox — sem caminhos locais fixos.

Para executar os notebooks:

```bash
poetry install --with dev
poetry run jupyter notebook docs/notebooks/
```

Ou abra-os diretamente no VS Code e execute as células com o suporte nativo a notebooks.

## Docker

### Usando a imagem pronta

Depois que o CI passa em `main`, `develop` ou `release/**`, o workflow Delivery valida e publica uma imagem Linux amd64. Docling/RapidOCR são serviços remotos da Toolbox, não dependências da imagem da aplicação.

```bash
docker pull ghcr.io/a11ydevs/acessilia:main
docker run --rm \
        --env-file .env \
        -p 8000:8000 \
        -p 8001:8001 \
        -v "$PWD/var:/app/var" \
        ghcr.io/a11ydevs/acessilia:main
```

Para reproduzir uma versão exata, use a tag `sha-<7 caracteres do commit>` ou o digest mostrado pelo workflow **Delivery**.

Para um servidor de producao com atualizacao automatica da `main`, use:

```bash
./scripts/setup-producao.sh
```

O procedimento completo de promocao, validacao e rollback esta em [docs/producao-systemd.md](docs/producao-systemd.md).

### Construindo localmente

```bash
docker compose up -d --build
```

O container expõe `8000` (API) e `8001` (web), persiste tudo em `./var` e roda o healthcheck em `/api/v1/health`.

### Extração estrutural remota

Use `STRUCTURER=toolbox`, `PIPELINE_ENGINE=pddl` e `TOOLBOX_PROVIDER=docling`. Configure `TOOLBOX_BASE_URL` para uma instância acessível; dentro do Docker, `http://host.docker.internal:8002` permite alcançar a Toolbox no host. Modelos e cache do provedor pertencem ao serviço Toolbox. O volume `/app/var` guarda os dados, temporários e logs da aplicação.

```bash
poetry run python -m scripts.check_toolbox
poetry run python -m scripts.manifest tests/fixtures/tutorials/java-oo-3pgs.pdf
```

O primeiro comando consulta saúde/capacidades; o segundo extrai e valida um manifesto pela API. A geração do PDDL é determinística. Vision/Data podem enriquecer imagens e tabelas antes do planejamento. A validação do plano é um dry-run opcional.

### Utilitários locais de fórmulas

O helper local preservado aceita `FORMULA_CODEFORMULA_TIMEOUT` (padrão: 120 segundos positivos e finitos, inclusive frações). Valores inválidos geram aviso e usam 120. O orçamento inclui preparação do recorte, inicialização do interpretador/modelo e inferência, inclusive downloads. Operações do SO e limpeza/leitura podem acrescentar overhead. O helper exige grupos de processos POSIX e o stack de modelos instalado separadamente; caso contrário retorna o fallback vazio.

A inferência usa um filho novo; em timeout, encerra e recolhe seu grupo de processos. O JSON é limitado a 8192 bytes e o LaTeX a 2000 caracteres; resultado inválido ou excessivo também retorna fallback. O orçamento não cobre o OCR anterior. Esses utilitários são separados do fluxo PDDL atual; seus testes com filhos locais não medem inferência real. Os antigos switches `DOCLING_FORMULA_ENRICHMENT` e `FORMULA_IMAGE_CASCADE` não têm consumidores na aplicação.

## Contribuindo

1. Fork o repositório.
2. Crie uma branch de feature.
3. Escreva testes para a nova funcionalidade.
4. Rode `poetry run pytest` e corrija falhas, erros ou skips.
5. Envie um pull request.

As regras detalhadas estão em [CONTRIBUTING.md](CONTRIBUTING.md).

## Licença

MIT © 2026 Jhonata Fernandes Cordeiro

