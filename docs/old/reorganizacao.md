# Proposta de Reorganização do Repositório — Acessília

## 1. Diagnóstico

- **10 pacotes soltos na raiz** (`adapters`, `config`, `core`, `exporters`, `filters`,
  `interfaces`, `pipeline`, `renderers`, `schemas`, `scripts`) — sem um pacote-raiz.
- **Exportação espalhada por 5 lugares que se entrelaçam** (`adapters/exporters`,
  `core/exporters`, `exporters`, `renderers`, `filters`) — difícil achar onde de fato acontece.
- **Dois orquestradores:** `core/orchestrator.py` (fachada) e `core/agents/team.py` (que na
  verdade é a classe `AccessibilityOrchestrator`, não um `Team` — o nome engana).
- **Frontend misturado com backend:** templates/estáticos vivem dentro de `interfaces/web/`,
  colados no código FastAPI.
- **Lixo versionado no Git:** `bot.lock`, `data/*.db`, `logs/*.log`, `output/`, e **169
  arquivos de `temp/cache/`** commitados (o `.gitignore` nem lista `temp/`).
- **Arquivos soltos/duplicados:** `ANALYSIS_REPORT.md`, `analysis-suggestions.txt`,
  `descrição-logo.txt`, um dump de log em `scripts/`, e `logo.png` duplicado (raiz +
  `interfaces/web/static/`).

---

## 2. Princípio da nova organização

O projeto passa a ter fronteiras claras: o **backend** só processa — recebe uma entrada e
devolve a resposta. Toda a comunicação com o usuário (web, Telegram, WhatsApp, CLI) fica no **frontend**, que chama o backend por um único ponto de entrada. `tests/` e `infra/` ficam no topo, e a raiz guarda só o que o ferramental exige ali (`pyproject.toml`, `poetry.lock`, `.gitignore`).

---

## 3. Estrutura-alvo

```
a11y-devs-describer/
├── pyproject.toml
├── poetry.lock
├── .gitignore
├── .env.example
├── README.md
│
├── infra/            # deploy / infraestrutura (Dockerfile, compose, nginx…)
│
├── backend/          # processamento dos dados
│   ├── __init__.py
│   ├── config/       # configurações do app
│   ├── agents/       # agentes de IA e orquestrador do pipeline
│   ├── ai/           # models e prompts
│   ├── pipeline/     # converte a saída dos agentes no documento acessível final
│   ├── export/       # gera os arquivos p/ download (TXT, DOCX, PDF, MP3) a partir do documento
│   ├── services/     # serviços de apoio: cache, histórico, e-mail, fila, limpeza
│   └── tools/        # utilitários genéricos e tools dos agentes
│
├── frontend/         # interfaces com o usuário (entrada/saída)
│   ├── web/          # FastAPI + templates + static
│   ├── telegram/
│   ├── whatsapp/
│   ├── cli/
│   └── run.py        # sobe as interfaces
│
├── tests/
│
├── docs/             # proposta.md, melhorias.md, schemas/…
├── scripts/          # apenas os .sh utilitários
└── var/              # runtime, gitignored: data/ logs/ temp/ output/ bot.lock
```

---

## 4. Limpeza do repositório

**Apagar:**
- Todos os `__pycache__/` (22 pastas) e `.pytest_cache/` — caches do Python
- `.coverage`, `*.pyc` soltos e `bot.lock` — artefatos de execução
- `scripts/corrigir_rapidocr_2026-06-10_16-55-54.txt` — dump de log dentro de `scripts/`
- `adapters/exporters/` — camada redundante (absorvida por `backend/export/`)
- `ANALYSIS_REPORT.md`, `analysis-suggestions.txt`, `descrição-logo.txt` — análises antigas (se obsoletas)

**Mover:**
- `logo.png` da raiz → `docs/` (é duplicata do de `static/`, mas guardamos como asset)
- `docs/melhoria-httpx-client-reutilizavel.txt`, `docs/implementacao_auditoria.txt` —
  notas `.txt` soltas no meio dos docs → revisar e consolidar nos `.md` (ou remover)

**Destrackear do Git** (some do versionamento, permanece no disco) — vão para `var/`:
- `temp/` (~1,9 MB, 169 caches), `output/` (~300 KB), `data/` (`*.db`), `logs/`
```bash
git rm -r --cached temp output data logs bot.lock
```

---