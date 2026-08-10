# Endpoints e APIs

O projeto expõe HTTP por **três servidores separados**, que sobem de formas diferentes. Confundi-los é o que mais gera dúvida, então a primeira coisa é separá-los:

| Servidor | O que é | Como sobe | Host/porta |
|----------|---------|-----------|------------|
| **API REST** | A API JSON principal do produto (enviar documento, consultar status, baixar resultado, histórico). Escrita por nós, em FastAPI. | Parte do `run.py` quando `ENABLED_INTERFACES` inclui `api`; ou isolada via `backend/api/run.py`. | `0.0.0.0:8000` |
| **Painel Web** | Interface HTML para humanos. Hoje é um **cliente fino** da API REST: renderiza as páginas e delega upload/status/download para a API. | Parte do `run.py` quando `ENABLED_INTERFACES` inclui `web`. | `0.0.0.0:8001` |
| **AgentOS** | Vitrine de inspeção dos agentes de IA. As rotas são **geradas automaticamente pelo Agno** — nós não escrevemos nenhuma. | Runtime separado: `python -m frontend.agent_os`. Não roda o pipeline. | `localhost:7777` |

`ENABLED_INTERFACES` (padrão `api,telegram,web`) controla o que sobe junto no `run.py`. O Telegram e o Painel Web são **clientes** da API REST (via `frontend/clients/api_client.py`); a API é a fonte da verdade.

---

## Parte 1 — API REST (backend/api, JSON)

Definida em [backend/api/app.py](../backend/api/app.py), com as rotas em [backend/api/routes/](../backend/api/routes/). É a API JSON de verdade: recebe `multipart/form-data` no upload e devolve **JSON** em tudo. Todas as rotas ficam sob o prefixo **`/api/v1`** e têm limite de requisições por IP. O processamento é **assíncrono**: o upload enfileira e responde na hora com um `task_id`; você acompanha por polling.

### Jobs (envio e acompanhamento)

| Método | Rota | O que faz | Retorno | Limite |
|--------|------|-----------|---------|--------|
| POST | `/api/v1/jobs` | Envia um documento para processar. Campos do form: `document_file`, `mode` (`normal` etc.), `custom_prompt` (teto de caracteres), `thinking_mode`, `email`, `source`. Valida extensão/tamanho e enfileira. | `202` com `task_id` e mensagem. `400` se arquivo ou prompt inválidos. | 5/min |
| GET | `/api/v1/jobs/{task_id}` | Consulta o estado de um job. | JSON `JobStatus`: `task_id`, `arquivo`, `status`, `progresso` (0–1), `etapa_atual`, `erros[]`, `download_url` (quando pronto), `criado_em`, `fim`. | — |
| POST | `/api/v1/jobs/{task_id}/cancel` | Cancela um job em andamento. | JSON `{task_id, status}`. | — |

### Download (resultado pronto)

| Método | Rota | O que faz | Retorno | Limite |
|--------|------|-----------|---------|--------|
| GET | `/api/v1/download/{token}` | Metadados do resultado de uma tarefa concluída. O `token` sai no `download_url` do job. | JSON `DownloadInfo`: `filename`, `stem`, `criado_em`, `formats[]` (cada um com `ext`, `label`, `size`, `url`). `404` se o token for inválido/expirado. | 10/min |
| GET | `/api/v1/download/{token}/{format}` | Baixa de fato um formato: `txt`, `docx`, `pdf`, `html`, `mp3` ou `zip`. | O arquivo em si. `400` formato inválido, `404` token/arquivo inexistente. | 20/min |

### Histórico e saúde

| Método | Rota | O que faz | Retorno | Limite |
|--------|------|-----------|---------|--------|
| GET | `/api/v1/history?limit=20` | Lista as últimas conversões (limit 1–100). | JSON `HistoryItem[]`: `task_id`, `arquivo`, `extensao`, `status`, `modo`, `pipeline`, `erro`, `resultado_resumo`, `tempo_segundos`, datas. | 30/min |
| GET | `/api/v1/stats` | Estatísticas agregadas. | JSON `{total, sucesso, erros, tempo_medio_segundos}`. | 30/min |
| GET | `/api/v1/health` | Checagem de saúde e conectividade do modelo. | JSON `{status, model_client, model_name, model_reachable, queue_size}`. | 30/min |

Observações:

- **Erros sempre em JSON** (`{"detail": "..."}`): `400` validação, `404` não encontrado, `429` rate limit, `500` erro interno. Há um limite global por IP além dos por rota.
- O campo `pipeline` no histórico registra qual motor rodou o job — `legacy` ou `pddl` (veja `PIPELINE_ENGINE` em [architecture.md](architecture.md)).
- Documentação interativa padrão do FastAPI em `GET /docs` e `GET /openapi.json`.

---

## Parte 2 — Painel Web (frontend/web, HTML)

Definido em [frontend/web/app.py](../frontend/web/app.py). É um app **renderizado no servidor** (templates Jinja2) que serve páginas HTML e, por baixo, chama a API REST. Não tem lógica de processamento própria: as rotas de upload e download apenas encaminham para `/api/v1`.

| Método | Rota | O que faz | Retorno |
|--------|------|-----------|---------|
| GET | `/` | Página inicial com o formulário de envio. | HTML. |
| GET | `/advanced` | Página avançada (prompt personalizado + modo "thinking"). | HTML. |
| POST | `/process` | Recebe o formulário e repassa o upload para `POST /api/v1/jobs`. | HTML com a confirmação/erro. |
| POST | `/advanced/process` | Igual, com `custom_prompt` e `thinking_mode`. | HTML. |
| GET | `/download/{token}` | Página de download; consulta a API e monta os links para `/api/v1/download/...`. | HTML listando os formatos. `404` se o token expirou. |
| — | `/static/*` | Arquivos estáticos (CSS, JS, imagens). | O arquivo. |

Ou seja: o Painel Web é a **cara** para humanos, a API REST é o **motor**. Um app de terminal, o Telegram ou um script externo falam direto com a API sem passar pelo painel.

---

## Parte 3 — AgentOS (gerado pelo Agno)

Ao instanciar o `AgentOS(...)` em [frontend/agent_os.py](../frontend/agent_os.py), o Agno **monta sozinho ~116 rotas REST em JSON** — o painel do Agno (os.agno.com) e o agent-ui consomem essas rotas. Nós não escrevemos nenhuma; vêm de brinde. Ele é ferramenta de **desenvolvimento/inspeção**: serve para conversar com cada agente isolado e ver sessões, memória, métricas e traces. **Não roda o pipeline** de acessibilidade.

O ponto importante: muitas dessas rotas existem sempre, mas só respondem algo útil se o recurso correspondente estiver configurado. No nosso setup registramos **dois agentes** (`VisionAgent` e `DataAgent`), com um SQLite de sessões (`agentos.db`), e nada de teams, workflows ou base de conhecimento. Daí quatro grupos:

- **Valem para o nosso setup** — `/agents/*` (falar com Vision/Data e ver execuções), `/sessions`, `/memories`, `/metrics` (os gráficos), `/traces`, além de `/health`, `/config`, `/info`, `/models`.
- **Existem mas vêm vazias** — `/teams`, `/workflows`, `/knowledge`, `/learnings`, `/eval-runs` (não registramos esses recursos). O pipeline hoje roda **fora** do AgentOS, então `/workflows` não mostra nada.
- **Presentes porém desligadas** — `/approvals`, `/components`, `/schedules`, `/service-accounts` (o próprio Agno marca "Disabled").
- **Utilitárias** — `GET /docs` (Swagger), `GET /redoc`, `GET /openapi.json`.

### Como conferir você mesmo

As rotas do AgentOS saem do que você registra; para ver a verdade atual, suba o runtime e consulte a especificação:

```bash
python -m frontend.agent_os            # sobe em localhost:7777
curl http://localhost:7777/openapi.json   # todas as rotas, geradas na hora
```

Se um dia registrarmos um Team, um Workflow ou uma base de conhecimento no `agent_os.py`, as rotas que hoje vêm vazias passam a responder — sem escrever endpoint nenhum.
