# Observabilidade

A documentação operacional fica em [observability/README.md](../observability/README.md). Este arquivo registra a arquitetura da observabilidade para evitar que a stack pareça parte obrigatória do runtime.

## Princípio

A observabilidade é opt-in. Sem `OBSERVABILITY_ENABLED=true`, a aplicação não expõe métricas, não envia traces e não escreve log JSON. Sem `docker compose --profile monitoring up -d`, os serviços externos não sobem.

O fluxo geral do `.env` não muda: a aplicação continua lendo `.env` como antes. A observabilidade só adiciona variáveis opcionais.

## Switch mestre e flags específicas

`OBSERVABILITY_ENABLED=true` liga as três partes da instrumentação da aplicação quando as flags específicas não foram definidas:

```bash
ENABLE_METRICS=true
LOG_JSON=true
ENABLE_TRACING=true
```

Se uma flag específica existir no `.env`, ela tem precedência. Isso permite, por exemplo, ligar só métricas com `OBSERVABILITY_ENABLED=false` e `ENABLE_METRICS=true`, ou ligar o pacote inteiro e desligar tracing para uma execução específica.

## Componentes

| Componente | Papel |
|------------|-------|
| `backend/observability.py` | wiring de métricas, traces e métricas de domínio |
| Prometheus | coleta `/metrics` e métricas de infra |
| Grafana | dashboards provisionados |
| Loki | busca e retenção local de logs |
| Alloy | coleta logs de `var/logs` e envia ao Loki |
| node-exporter | CPU, memória, disco e pressão de CPU |
| Langfuse | traces de LLM via OTLP |
| `observability/frontend/` | painel próprio e anotações locais |

Promtail não faz parte da stack. O coletor de logs é o Grafana Alloy.

## Dados

Os dados ficam separados por responsabilidade:

| Dado | Origem | Destino |
|------|--------|---------|
| Request rate, latência e status HTTP | FastAPI instrumentado | Prometheus |
| Fila, jobs, exportações, outputs e LLM por agente | métricas de domínio do Acessília | Prometheus |
| Logs humanos e JSON | Loguru em `var/logs` | Loki via Alloy |
| Traces de LLM | OpenTelemetry + AgnoInstrumentor | Langfuse |
| Anotações da revisão | painel próprio | `observability/data/observability.db` |

O painel próprio centraliza a leitura desses dados, mas não substitui Prometheus, Grafana, Loki ou Langfuse. Ele serve como uma visão curta e anotável para desenvolvimento e revisão de PR.

O tráfego HTTP aparece separado entre requisições de usuário, tráfego interno da observabilidade e total da API. Essa separação evita que `/metrics`, healthcheck, stats e histórico contaminem a leitura dos testes manuais.

O painel atualiza cards e gráficos de tempo real a cada 1s. O snapshot mais pesado, com logs, histórico e anotações, roda a cada 10s. As amostras novas dependem do scrape do Prometheus, configurado em 5s para API e `node-exporter`.

GPU não vem do `node-exporter`. O painel consulta métricas NVIDIA/DCGM quando elas existirem no Prometheus; sem um exporter compatível, os cards de GPU ficam sem dado.

As chamadas de agente do Agno também alimentam métricas agregadas no Prometheus: tokens, TTFT, custo, duração, modelo e provedor quando esses campos aparecem em `RunOutput.metrics`. Prompt, resposta e spans completos ficam no Langfuse para não colocar conteúdo sensível em labels ou séries de Prometheus.

## Falhas

Observabilidade não deve derrubar processamento de documento. Se uma dependência opcional faltar, um endpoint estiver fora do ar ou um coletor não responder, a aplicação registra aviso e segue. A perda esperada é apenas de métricas, logs estruturados ou traces daquele período.

## Langfuse

Langfuse está no profile `monitoring` por enquanto porque os traces de LLM são parte importante da revisão do comportamento dos agentes. Ele é mais pesado que Prometheus/Loki/Grafana, então pode ser separado no futuro se o custo local ficar alto.
