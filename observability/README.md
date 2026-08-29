# Observabilidade

A observabilidade do Acessilia é opt-in. A aplicacao continua leve no uso normal e nao sobe Prometheus, Grafana, Loki, Alloy, Langfuse nem o painel proprio quando o Docker e iniciado sem o profile de monitoramento.

Para ligar a stack completa, duas coisas precisam estar ativas:

```dotenv
# .env
OBSERVABILITY_ENABLED=true
```

```bash
docker compose --profile monitoring up -d
```

`OBSERVABILITY_ENABLED=true` faz a aplicacao emitir metricas, logs estruturados e traces. O profile `monitoring` sobe as ferramentas que coletam e exibem esses dados. Se uma dessas partes faltar, a observabilidade fica incompleta.

Se o switch mestre estiver desligado, ainda da para ativar partes isoladas:

```dotenv
ENABLE_METRICS=true
LOG_JSON=true
ENABLE_TRACING=true
```

Quando `OBSERVABILITY_ENABLED=true`, essas tres flags herdam `true` se nao estiverem definidas. Se uma flag especifica estiver no `.env`, ela tem prioridade. Para o switch mestre ligar tudo, deixe `ENABLE_METRICS`, `LOG_JSON` e `ENABLE_TRACING` comentadas ou remova essas linhas.

## Enderecos locais

| Servico | URL | Uso |
|---------|-----|-----|
| Painel proprio | http://localhost:8010 | Interface central da observabilidade |
| Grafana | http://localhost:3000 | Dashboards Prometheus e Loki |
| Prometheus | http://localhost:9090 | Consultas PromQL, targets e series brutas |
| Loki | http://localhost:3100 | Logs brutos |
| Langfuse | http://localhost:3001 | Traces de LLM, prompts, respostas, tokens e latencia |
| Tempo | http://localhost:3200 | Tracing distribuido da infraestrutura quando houver coletor ativo |
| Locust | http://localhost:8089 | Testes de carga e comportamento sob estresse |
| API | http://localhost:8000 | Aplicacao principal e endpoint `/metrics` |
| Console Agno | http://localhost:8010/agno | Chat direto com agentes detectados pelo AgentOS |

Essas portas sao para uso local. Nao exponha Grafana, Prometheus, Loki ou Langfuse publicamente sem autenticacao e rede adequada.

## O que existe na stack

| Componente | Funcao |
|------------|--------|
| Prometheus | coleta metricas da API, do painel e da infraestrutura |
| Grafana | mostra dashboards sobre Prometheus e Loki |
| Loki | armazena e consulta logs |
| Alloy | coleta logs locais e envia para o Loki |
| node-exporter | expoe CPU, memoria, disco, rede e metricas do host |
| Langfuse | recebe traces de LLM via OTLP |
| observability-frontend | painel proprio em `:8010` |

Promtail nao e mais usado. A coleta de logs passa pelo Grafana Alloy.

Tempo e Locust aparecem no painel quando os endpoints configurados estiverem ativos. Por padrao, o painel tenta ler `TEMPO_URL=http://localhost:3200` e `LOCUST_URL=http://localhost:8089` fora do Docker, ou os valores definidos no `.env`.

## Organizacao dos arquivos

```text
observability/
├── config.py           parametros de carga e consultas Prometheus
├── data/               banco local do painel proprio
├── frontend/           templates, CSS e JavaScript da interface
├── instrumentacao/     testes de metricas, tracing e painel
├── metricas/           resumo tabular do Prometheus
├── src/                nucleo do painel, adapters, storage e contratos
├── stack/              Prometheus, Grafana, Loki e Alloy
└── testes_de_carga/    cenario Locust
```

O codigo que instrumenta a API fica em `backend/observability.py`, porque roda junto da aplicacao. A pasta `observability/` concentra a stack externa, o painel, consultas, testes e dados proprios da observabilidade.

O painel foi organizado para ser acoplavel. `observability/src` contem o servidor FastAPI, configuracao, contratos, adapters de Prometheus/Loki/AgentOS e storage SQLite. `observability/frontend` contem apenas a camada visual. Os imports antigos em `observability/frontend/app.py`, `store.py` e `agno_client.py` continuam como wrappers para compatibilidade, mas o caminho canonico e `observability.src`.

Para adaptar em outro projeto, ajuste principalmente:

```dotenv
OBSERVABILITY_PROJECT_NAME=Acessilia
OBSERVABILITY_METRIC_PREFIX=acessilia
OBSERVABILITY_PROMETHEUS_API_JOB=acessilia-api
OBSERVABILITY_LOKI_QUERY={job="acessilia"}
OBSERVABILITY_API_HEALTH_PATH=/api/v1/health
OBSERVABILITY_API_STATS_PATH=/api/v1/stats
OBSERVABILITY_API_HISTORY_PATH=/api/v1/history?limit=20
OBSERVABILITY_FRONTEND_TRACING=false
```

Trocar Prometheus, Loki ou o storage deve ficar concentrado nos adapters em `observability/src/integrations` ou `observability/src/storage`, mantendo as rotas e a UI estaveis.

## Painel proprio

O painel em http://localhost:8010 centraliza os dados mais importantes para revisao e teste manual.

| Aba | Conteudo |
|-----|----------|
| Visao geral | status, health, historico, requisicoes reais, requisicoes internas, erros HTTP e graficos em tempo real |
| Pipeline | fila, jobs ativos, jobs por status, erros por etapa, conversoes por minuto e latencia de conversao |
| Metricas detalhadas | exportacoes por formato, tamanho dos outputs e series de saida |
| Logs | ultimas linhas consultadas no Loki |
| Infra | CPU, RAM, disco, rede, targets, Alloy e GPU quando houver exporter compativel |
| LLM | chamadas por agente, falhas, duracao, TTFT, tokens, cache, custo, modelos, provedor, Langfuse e Tempo |
| Anotacoes | notas locais de revisao, incidente, teste ou acompanhamento de PR |

As anotacoes ficam em `observability/data/observability.db`. Esse banco pertence ao painel de observabilidade e nao interfere nos bancos principais da aplicacao. O arquivo `.db` nao deve ser versionado.

## Console Agno

O Console Agno fica em http://localhost:8010/agno e permite conversar diretamente com agentes detectados pelo AgentOS, sem passar pela pipeline completa.

Configuracao local:

```dotenv
AGNO_OS_URL=http://host.docker.internal:7777
AGNO_OS_SECURITY_KEY=
AGNO_CONSOLE_STORE_REASONING=false
```

Esse valor atende o caso comum de painel no Docker e AgentOS rodando no host. Se o painel estiver rodando fora do Docker, use `AGNO_OS_URL=http://localhost:7777`. Se o AgentOS estiver em outro container ou em outra maquina, ajuste `AGNO_OS_URL` no `.env`.

O painel usa `AGNO_OS_URL` para consultar `/health`, `/agents` e `/teams`. Quando `AGNO_OS_SECURITY_KEY` estiver preenchido, o proxy local envia `Authorization: Bearer ...` para o AgentOS.

`AGNO_CONSOLE_STORE_REASONING=false` mantem o modo seguro: eventos de reasoning sao resumidos antes de ir para a interface e para o SQLite. Use `true` apenas em ambiente local controlado, quando for necessario inspecionar o texto bruto.

Nesta etapa, o console:

| Recurso | Estado |
|---------|--------|
| Descoberta de agentes | ativo |
| Descoberta de times | ativo |
| Chat direto com agente | ativo |
| Chat direto com time | ativo |
| Historico de sessoes | ativo |
| Metricas por resposta | ativo |
| Comparativo por agente/modelo | ativo |
| Relatorio Markdown | ativo |
| Workflows | preparado na interface, ainda sem execucao |
| Step functions | preparado na interface, ainda sem execucao |

As chamadas passam pelo backend do painel para evitar problema de CORS e centralizar a coleta de metricas por conversa. O proxy aceita eventos em NDJSON ou SSE (`event:`/`data:`) e entrega um JSON por linha para a interface.

Cada execucao do Console Agno recebe `trace_id`, `run_id` e `session_id`. Esses IDs sao enviados no stream, persistidos com o run e usados como base de correlacao com traces, metricas, logs e investigacoes futuras no Langfuse ou Tempo.

## Atualizacao em tempo real

O painel usa dois ritmos:

| Ritmo | Atualiza | Motivo |
|-------|----------|--------|
| 1s | cards e graficos de comportamento recente | acompanhar testes manuais em tempo real |
| 10s | snapshot geral, status, logs, historico e anotacoes | evitar consultas pesadas sem necessidade |

O Prometheus coleta a API e o `node-exporter` a cada 5s. A interface pode redesenhar a cada 1s, mas novas amostras reais so aparecem quando o Prometheus recebe outro scrape.

## Requisicoes reais e internas

O painel separa o trafego HTTP para nao poluir a leitura de teste:

| Metrica | Significado |
|---------|-------------|
| `Req/s usuarios` | requisicoes da aplicacao, sem `/metrics`, healthcheck, stats, historico e chamadas do painel |
| `Req/s interno` | trafego gerado por Prometheus, healthchecks, painel e endpoints auxiliares |
| `Req/s total` | tudo que chega na API |

Durante testes manuais, use `Req/s usuarios` como leitura principal. `Req/s interno` e esperado mesmo sem usuario real, porque a propria observabilidade consulta a aplicacao.

## Erros HTTP

| Grupo | Significado |
|-------|-------------|
| `4xx` | erro de cliente, rota inexistente, validacao, limite ou requisicao invalida |
| `5xx` | erro de servidor, excecao interna ou falha de infraestrutura |

Quando nao houver erro, o painel mostra `0%`. `Sem dado` significa que a serie nao existe, a fonte esta indisponivel ou ainda nao houve amostra suficiente no Prometheus.

## Metricas da aplicacao

As metricas proprias do Acessilia ficam separadas das metricas operacionais.

| Metrica | Significado |
|---------|-------------|
| `acessilia_queue_size` | quantidade de jobs aguardando na fila |
| `acessilia_jobs_active` | jobs em processamento por origem e modo |
| `acessilia_jobs_total` | jobs por status, origem e modo |
| `acessilia_conversion_duration_seconds` | duracao dos jobs |
| `acessilia_pipeline_errors_total` | falhas por etapa |
| `acessilia_exports_total` | exportacoes por formato |
| `acessilia_output_bytes` | tamanho dos outputs por formato |

## Metricas de LLM e Agno

As metricas de LLM da aplicacao principal continuam no prefixo `acessilia_llm_*`. O Console Agno tambem exporta series proprias no prefixo `acessilia_agno_*`, voltadas ao chat direto e ao comparativo da interface.

| Metrica | Significado |
|---------|-------------|
| `acessilia_llm_calls_total` | chamadas por agente |
| `acessilia_llm_failures_total` | falhas por agente |
| `acessilia_llm_duration_seconds` | duracao das chamadas |
| `acessilia_llm_time_to_first_token_seconds` | TTFT quando reportado |
| `acessilia_llm_tokens_total` | tokens de entrada, saida, total, reasoning, cache e audio quando reportados |
| `acessilia_llm_cost_total` | custo reportado pelo provedor |
| `acessilia_llm_content_chars` | tamanho agregado de prompt e resposta |
| `acessilia_llm_model_info` | modelo e provedor observados por agente |
| `acessilia_agno_chat_calls_total` | chamadas do Console Agno por entidade, modelo e status |
| `acessilia_agno_chat_failures_total` | falhas do chat direto por tipo de erro |
| `acessilia_agno_chat_duration_seconds` | duracao das execucoes do Console Agno |
| `acessilia_agno_chat_ttft_seconds` | TTFT medido no proxy local |
| `acessilia_agno_chat_tokens_total` | tokens de entrada, saida e reasoning quando reportados |
| `acessilia_agno_chat_tool_calls_total` | chamadas de ferramentas por entidade e status |
| `acessilia_agno_chat_reasoning_steps_total` | quantidade de eventos de reasoning observados |
| `acessilia_agno_chat_cost_total` | custo reportado pelo provedor para chamadas do console |
| `acessilia_agno_chat_content_chars` | tamanho agregado de prompt e resposta do console |

O painel proprio mostra agregados seguros. Prompt e resposta ficam no SQLite local do console. Prompts, respostas, IDs de sessao e payloads internos nao entram como label no Prometheus para evitar vazamento de conteudo e explosao de cardinalidade.

Se o provedor local nao retornar tokens, TTFT ou custo, o painel mostra `sem dado` ou `0`. Isso indica ausencia de fonte para aquele campo, nao erro da interface.

## GPU

`node-exporter` nao coleta GPU, VRAM, temperatura nem watts. O painel ja consulta metricas no padrao NVIDIA/DCGM (`DCGM_FI_DEV_*`) e mostra esses dados quando existir um exporter compativel no Prometheus.

Sem exporter de GPU configurado, os cards de GPU ficam como `sem dado`. Isso evita misturar consumo geral da maquina com consumo real da GPU.

## Logs

Com `LOG_JSON=true`, o logger escreve log estruturado alem do log humano. O Alloy coleta:

```text
var/logs/acessilia_*.json.log
var/logs/bot_*.log
```

O log JSON facilita filtro por nivel, modulo e mensagem no Loki. O log humano continua disponivel para leitura direta.

## Langfuse

Langfuse sobe junto com `docker compose --profile monitoring up -d`.

Configuracao local padrao dentro do Docker:

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=http://langfuse-web:3000/api/public/otel
LANGFUSE_PUBLIC_KEY=pk-lf-acessilia-local
LANGFUSE_SECRET_KEY=sk-lf-acessilia-local
```

Se a API estiver fora do Docker e o Langfuse estiver no compose:

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:3001/api/public/otel
```

`LANGFUSE_PUBLIC_KEY` e `LANGFUSE_SECRET_KEY` viram o header Basic Auth automaticamente. `OTEL_EXPORTER_OTLP_HEADERS` tem prioridade quando for necessario apontar para outro coletor.

O painel tambem pode emitir spans OpenTelemetry proprios quando `OBSERVABILITY_FRONTEND_TRACING=true` e `OTEL_EXPORTER_OTLP_ENDPOINT` estiverem definidos. Sem essa flag, a emissao de spans do painel fica desativada e o restante continua funcionando.

## Consulta tabular

Para gerar um resumo numerico direto do Prometheus:

```bash
poetry run python observability/metricas/consultar.py
```

As consultas ficam em `observability/config.py`. Metrica ausente aparece como `-`, sem interromper o relatorio.

## Testes de carga

Com a API no ar:

```bash
poetry run locust -f observability/testes_de_carga/locustfile.py
```

Abra http://localhost:8089 para acompanhar.

Por padrao, a carga usa rotas de leitura. `ENVIAR_DOCUMENTOS=true` envia documentos de verdade, dispara LLM e pode gerar custo no provedor.

## Validacao local

Antes de abrir PR, rode:

```bash
poetry run pytest observability/instrumentacao -q
poetry run pytest -q
poetry check --lock
docker compose --profile monitoring config
git diff --check
```

Para teste visual, suba a stack, abra http://localhost:8010 e navegue pelas abas do painel.

## Nota sobre recursos

Langfuse e mais pesado que o restante da stack porque sobe web, worker, Postgres, ClickHouse, Redis e MinIO. Se a maquina ficar lenta, desligue o profile `monitoring` ou rode Langfuse em uma maquina separada.
