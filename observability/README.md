# Observabilidade

A observabilidade do Acessilia e opt-in. A aplicacao continua leve no uso normal e nao sobe Prometheus, Grafana, Loki, Alloy, Langfuse nem o painel proprio quando o Docker e iniciado sem o profile de monitoramento.

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
| API | http://localhost:8000 | Aplicacao principal e endpoint `/metrics` |

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

## Organizacao dos arquivos

```text
observability/
├── config.py           parametros de carga e consultas Prometheus
├── data/               banco local do painel proprio
├── frontend/           interface central de observabilidade
├── instrumentacao/     testes de metricas, tracing e painel
├── metricas/           resumo tabular do Prometheus
├── stack/              Prometheus, Grafana, Loki e Alloy
└── testes_de_carga/    cenario Locust
```

O codigo que instrumenta a API fica em `backend/observability.py`, porque roda junto da aplicacao. A pasta `observability/` concentra a stack externa, o painel, consultas, testes e dados proprios da observabilidade.

## Painel proprio

O painel em http://localhost:8010 centraliza os dados mais importantes para revisao e teste manual.

| Aba | Conteudo |
|-----|----------|
| Visao geral | status, health, historico, requisicoes reais, requisicoes internas, erros HTTP e graficos em tempo real |
| Pipeline | fila, jobs ativos, jobs por status, erros por etapa, conversoes por minuto e latencia de conversao |
| Metricas detalhadas | exportacoes por formato, tamanho dos outputs e series de saida |
| Logs | ultimas linhas consultadas no Loki |
| Infra | CPU, RAM, disco, rede, targets, Alloy e GPU quando houver exporter compativel |
| LLM | chamadas por agente, falhas, duracao, TTFT, tokens, cache, custo, modelos e provedor |
| Anotacoes | notas locais de revisao, incidente, teste ou acompanhamento de PR |

As anotacoes ficam em `observability/data/observability.db`. Esse banco pertence ao painel de observabilidade e nao interfere nos bancos principais da aplicacao. O arquivo `.db` nao deve ser versionado.

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

As chamadas dos agentes Agno alimentam metricas de LLM quando o provedor retorna esses dados.

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

O painel proprio mostra agregados seguros. Prompt, resposta completa, eventos internos e spans detalhados ficam no Langfuse. Esses dados nao entram como label no Prometheus para evitar vazamento de conteudo e explosao de cardinalidade.

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
