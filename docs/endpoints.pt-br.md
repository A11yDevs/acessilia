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
| POST | `/api/v1/jobs` | Envia um documento para processar. Campos do form: `document_file`, `mode` (`detalhado`, `medio`, `normal`, `baixo` ou `ocr`; padrão `normal`), `custom_prompt` (deve ser vazio), `thinking_mode` (deve ser falso), `email`, `source`. Valida extensão/tamanho e enfileira. | `202` com `task_id`, `job_token`, `position` e mensagem. `400` para entrada inválida; `422` para opções não suportadas. | 5/min |
| GET | `/api/v1/jobs/{task_id}` | Consulta o estado de um job. Requer `X-Job-Token`. | JSON `JobStatus`: `task_id`, `arquivo`, `status`, `progresso` (0–1), `etapa_atual`, `erros[]`, `download_url` (quando pronto), `email_delivery`, `criado_em`, `fim`. | 60/min |
| POST | `/api/v1/jobs/{task_id}/cancel` | Solicita o cancelamento de um job. Requer `X-Job-Token`. | JSON `{task_id, status}`. | 10/min |

### Download (resultado pronto)

| Método | Rota | O que faz | Retorno | Limite |
|--------|------|-----------|---------|--------|
| GET | `/api/v1/download/{token}` | Metadados do resultado de uma tarefa concluída. O `token` sai no `download_url` do job. | JSON `DownloadInfo`: `filename`, `stem`, `criado_em`, `formats[]` (cada um com `ext`, `label`, `size`, `url`). `404` se o token for inválido/expirado. | 10/min |
| GET | `/api/v1/download/{token}/{format}` | Baixa de fato um formato: `txt`, `docx`, `pdf`, `pdf_ua`, `html`, `mp3` ou `zip` (o pacote com tudo). | O arquivo em si. `400` formato inválido, `404` token/arquivo inexistente. | 20/min |

### Histórico e saúde

| Método | Rota | O que faz | Retorno | Limite |
|--------|------|-----------|---------|--------|
| GET | `/api/v1/history?limit=20` | Lista as últimas conversões (limit 1–100). Requer o token Bearer de observabilidade. | JSON `HistoryItem[]`: `task_id`, `arquivo`, `extensao`, `status`, `modo`, `pipeline`, `erro`, `resultado_resumo`, `tempo_segundos`, datas. | 30/min |
| GET | `/api/v1/stats` | Estatísticas agregadas. Requer o token Bearer de observabilidade. | JSON `{total, sucesso, erros, tempo_medio_segundos}`. | 30/min |
| GET | `/api/v1/health` | Checagem de saúde e conectividade do modelo. | JSON `{status, model_client, model_name, model_reachable, queue_size}`. | 30/min |
| GET | `/api/v1/logs` | Lista os arquivos de log retidos pela aplicação. Requer `Authorization: Bearer <OBSERVABILITY_API_TOKEN>`. | JSON `{files: [{name, size_bytes}]}`. | 30/min |
| GET | `/api/v1/logs/{filename}` | Baixa um arquivo de log completo, inclusive arquivos `.zip` de dias anteriores. Requer o mesmo token. | Arquivo para download; `404` se não existir. | 30/min |

`OBSERVABILITY_API_TOKEN` é uma senha de leitura definida no `.env` para histórico, estatísticas e logs; vazio, elas ficam desabilitadas. Envie-a no cabeçalho, por exemplo: `curl -H "Authorization: Bearer SEU_TOKEN" http://localhost:8000/api/v1/logs`. Use HTTPS ou uma rede privada para não expor a senha e o conteúdo. As rotas de logs servem apenas arquivos `bot_*` em `LOGS_DIR`, dentro da retenção configurada pelo logger (30 dias). Ferramentas de análise podem baixar os arquivos e processá-los sem depender de uma stack específica. Os logs de acesso do Uvicorn continuam disponíveis em `docker compose logs`.

Observações:

- **Erros sempre em JSON** (`{"detail": "..."}`): `400` validação, `404` não encontrado, `429` rate limit, `500` erro interno. Há um limite global por IP além dos por rota.
- O campo `pipeline` no histórico registra qual motor rodou o job — `legacy` ou `pddl` (veja `PIPELINE_ENGINE` em [architecture.md](architecture.md)).
- Documentação interativa padrão do FastAPI em `GET /docs` e `GET /openapi.json`.

### Acesso aos jobs, opções de processamento e recuperação

- `POST /api/v1/jobs` aceita submissões sem login e devolve `job_token` além de `task_id`/`position`. Guarde o token: `GET /api/v1/jobs/{task_id}` e `POST /api/v1/jobs/{task_id}/cancel` exigem `X-Job-Token: <job_token>`. Token ausente/incorreto retorna 404 sem revelar se o job existe. Jobs sem credencial de autorização persistida não podem ser acessados; reenvie o documento se o token do job estiver indisponível.
- Histórico e estatísticas globais exigem `Authorization: Bearer <OBSERVABILITY_API_TOKEN>`, assim como logs. Sem configuração retornam 503; sem credencial válida, 401. Esse token é somente leitura e não substitui o token de job.
- O cliente `ApiClient` guarda automaticamente tokens das submissões feitas por sua instância. Um novo cliente pode passar `job_token` explicitamente a `get_job_status`/`cancel_job`. Para histórico/estatísticas, instancie com `observability_token`. Guarde o token devolvido se precisar reconectar após reinício do cliente.
- Cancelamento ativo sinaliza `cancelling` enquanto termina a limpeza; `cancelled` indica o encerramento. Operações assíncronas são interrompidas. Threads já iniciadas são aguardadas antes de remover seus arquivos; cancelar não mata uma thread nem encerra remotamente o provider. Trabalho síncrono continua limitado pelos timeouts configurados dos providers.
- A persistência SQLite executa fora do loop assíncrono. Falha ao enfileirar remove a solicitação persistida e o upload; gravações atrasadas não substituem estados terminais. No reinício, `cancelling` é finalizado como `cancelled`.
- O painel redireciona o envio para `/jobs/{task_id}` e mantém o token em cookie HttpOnly, SameSite=Lax, limitado àquela página, com Secure em HTTPS. A página não coloca o token em URLs ou HTML, não usa cache e permite acompanhar/baixar o resultado mesmo se o e-mail falhar. O cookie dura sete dias; o link salvo exige o mesmo navegador e cookie. `email_delivery` informa `pending`, `sent`, `failed` ou `unknown` (entrega não confirmada após reinício).
- `custom_prompt` não vazio e `thinking_mode=true` retornam 422 no pipeline ativo. Os controles correspondentes ficam desabilitados no painel avançado. Os campos ainda são aceitos com valores vazios/falsos por compatibilidade.
- Pedidos pendentes são persistidos antes do 202 em `DATA_DIR/history.db`. No reinício, jobs enfileirados com upload disponível voltam à fila; jobs que estavam processando são marcados como interrompidos, exigindo reenvio. Jobs concluídos mantêm seu status/link persistido; os downloads continuam sujeitos à expiração normal. Upload ausente produz erro explícito.
- Use um único worker de API por `DATA_DIR`, em armazenamento local persistente. A trava `api-worker.lock` impede inicialização concorrente no mesmo diretório; não há suporte a réplicas com filas independentes nem a uma fila distribuída. O Compose usa o volume persistente existente em `var/`.
- Plano/dry-run PDDL não é certificado de acessibilidade: metadados incluem `pddl_validation_only=true` e `accessibility_verified=false`. Métodos sem implementação não declaram sucesso real. Os enriquecimentos e exportadores executam fora dessa simulação.

---

## Parte 2 — Painel Web (frontend/web, HTML)

Definido em [frontend/web/app.py](../frontend/web/app.py). É um app **renderizado no servidor** (templates Jinja2) que serve páginas HTML e, por baixo, chama a API REST. Não tem lógica de processamento própria: as rotas de upload e download apenas encaminham para `/api/v1`.

| Método | Rota | O que faz | Retorno |
|--------|------|-----------|---------|
| GET | `/` | Página inicial com o formulário de envio. | HTML. |
| GET | `/advanced` | Página avançada; controles de prompt/thinking não suportados ficam desabilitados. | HTML. |
| POST | `/process` | Recebe o formulário e repassa o upload para `POST /api/v1/jobs`. | `303` para `/jobs/{task_id}` com cookie privado; HTML em caso de erro. |
| POST | `/advanced/process` | Mesmo envio; `custom_prompt` não vazio ou `thinking_mode` verdadeiro retorna 422. | HTML. |
| GET | `/jobs/{task_id}` | Acompanha o job e permite recuperar seus arquivos. Exige o cookie privado da submissão. | HTML com atualização automática enquanto pendente; `404` sem autorização, `503` se a API estiver indisponível. |
| GET | `/download/{token}` | Página de download; consulta a API e monta os links para `/api/v1/download/...`. | HTML listando os formatos. `404` se o token expirou. |
| — | `/static/*` | Arquivos estáticos (CSS, JS, imagens). | O arquivo. |

Ou seja: o Painel Web é a **cara** para humanos, a API REST é o **motor**. Um app de terminal, o Telegram ou um script externo falam direto com a API sem passar pelo painel.

---

## Parte 3 — AgentOS (gerado pelo Agno)

Ao instanciar o `AgentOS(...)` em [frontend/agent_os.py](../frontend/agent_os.py), o Agno **monta sozinho uma centena de rotas REST em JSON** — o painel do Agno (os.agno.com) e o agent-ui consomem essas rotas. Nós não escrevemos nenhuma; vêm de brinde. A lista exata varia com a versão do Agno e com o que está registrado, então a fonte da verdade é o `openapi.json` do runtime (veja "Como conferir você mesmo", no fim). Ele é ferramenta de **desenvolvimento/inspeção**: serve para conversar com cada agente isolado e ver sessões, memória, métricas e traces. **Não roda o pipeline** de acessibilidade.

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
