# Observabilidade

Tudo que tem a ver com medir o sistema fica aqui: a stack que sobe no Docker, os testes de carga, a leitura de métricas e os testes da instrumentação.

```
observability/
├── config.py           parâmetros de configuração da carga e das métricas
├── stack/              Prometheus, Grafana, Loki, Promtail (configs do compose)
├── testes_de_carga/    cenário Locust, com bateria de degraus
├── metricas/           lê o Prometheus e imprime como tabela
└── instrumentacao/     testes do wiring em backend/observability.py
```

## Onde os dados aparecem

Cada ferramenta guarda o dado dela e tem sua própria tela. O Grafana é o lugar central: ele lê o Prometheus e o Loki na mesma página.

| O quê | Vai para | Onde ver |
|-------|----------|----------|
| Requisições, latência, erros | Prometheus | **Grafana em http://localhost:3000** (dashboard "Acessília — visão geral"). O Prometheus cru fica em http://localhost:9090 |
| Logs da aplicação | Loki | Mesmo Grafana, painel de logs no fim do dashboard |
| CPU e memória da máquina | Prometheus (node-exporter) | Mesmo dashboard |
| Traces das chamadas de LLM | Langfuse ou outro coletor OTLP | Interface do Langfuse (Cloud ou self-hosted) |
| Resultado do teste de carga | Locust | Tela própria em http://localhost:8089 enquanto roda |
| Tokens e custo por execução | SQLite do Agno | Já gravado por execução; visível pelo AgentOS/agent-ui |

O Grafana sobe sem login e com os datasources e o dashboard já cadastrados, então é abrir e ver. Como não tem senha, não exponha a porta 3000 para fora da máquina.

Se os painéis aparecerem vazios, quase sempre é uma destas: a API está sem `ENABLE_METRICS=true`, ou o profile `monitoring` não está no ar.

No primeiro minuto depois de subir a stack é normal ver "—" ou gráfico vazio: as consultas usam `rate` sobre uma janela de 1 minuto e precisam de pelo menos duas coletas para calcular alguma coisa.

## Subir a stack

```bash
docker compose --profile monitoring up -d
```

O `docker compose up` normal continua subindo só a aplicação. Para derrubar só o monitoramento:

```bash
docker compose --profile monitoring down
```

## Ligar na aplicação

As métricas e os traces são opcionais e ficam desligados por padrão. O jeito mais
simples de ligar tudo de uma vez é:

```bash
OBSERVABILITY_ENABLED=true
```

Esse switch liga as três partes principais da observabilidade quando a flag
específica não foi definida manualmente:

```bash
ENABLE_METRICS=true    # expõe /metrics para o Prometheus
LOG_JSON=true          # log estruturado, melhor para filtrar no Loki
ENABLE_TRACING=true    # traces de LLM (precisa do endpoint OTLP)
```

Se `OBSERVABILITY_ENABLED=false` ou estiver ausente, cada parte continua podendo
ser ligada sozinha com a própria variável.

E instale as dependências opcionais:

```bash
poetry install --extras observability
```

O detalhamento de cada variável está em [docs/observability.md](../docs/observability.md).

## Testes de carga

Ajuste [config.py](config.py) e rode com a API no ar:

```bash
poetry run locust -f observability/testes_de_carga/locustfile.py
```

Abra http://localhost:8089 para acompanhar. Não precisa passar `--users` nem `--spawn-rate`: a bateria vem da config.

A sequência de cada rodada é: aquecimento (requisições descartadas, para o primeiro degrau não pagar o custo de sistema frio), subida até o número de usuários, a janela de medição, e descanso antes do próximo degrau para as filas esvaziarem. A bateria para sozinha se as falhas passarem do limite, já que aí o teto apareceu.

Os monitores de health entram por cima do degrau e não descontam dele, porque na produção esse tráfego é do Docker em ritmo fixo e não cresce junto com os usuários.

Qualquer valor aceita variável de ambiente:

```bash
DEGRAUS="5,10,20" DURACAO_POR_DEGRAU=5m poetry run locust -f observability/testes_de_carga/locustfile.py
```

Por padrão a carga só bate nas rotas de leitura, medindo o custo de servir requisição. `ENVIAR_DOCUMENTOS=true` passa a submeter documentos de verdade, o que dispara LLM e gasta dinheiro no provedor.

O tempo que o Locust mede é do lado cliente, com rede. A latência interna aparece no Prometheus, e os dois números não batem exatamente.

### Métricas em tabela

Quando quiser um número para colar em algum lugar em vez de um print do gráfico:

```bash
poetry run python observability/metricas/consultar.py
```

## Por que o código de instrumentação fica em backend/

`backend/observability.py` é código de produção: roda junto com o servidor e é o que faz a aplicação emitir traces e métricas sob tráfego real. Ele fica lá, e não aqui, porque `backend/api/app.py` o importa no startup — trazê-lo para cá criaria uma dependência circular entre pacotes, já que ele também importa `backend.config` e `backend.tools`.

Esta pasta é o lado de fora: sobe as ferramentas, gera carga e confere o resultado. `instrumentacao/` guarda os testes daquele módulo, perto do resto do assunto.
