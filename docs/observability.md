# Observability

Everything about measuring the system lives in [observability/](../observability/): the Docker stack, the load tests, the metric queries and the tests for the instrumentation. That folder's README covers how to run it and where each number shows up.

One piece sits outside it. [backend/observability.py](../backend/observability.py) is the runtime wiring — production code that makes the running application emit traces and metrics under real traffic. It stays in `backend/` because `backend/api/app.py` imports it at startup, and moving it would create a circular dependency between packages.

Everything here is off by default. With no extra environment variables the runtime loads no tracing library, opens no extra port, and behaves exactly as before. This is deliberate: observability is an accessory, and a document conversion must never fail because a collector is down.

If you want the whole bundle on, set `OBSERVABILITY_ENABLED=true`. That turns on
`ENABLE_METRICS`, `LOG_JSON` and `ENABLE_TRACING` by default, but each flag still
accepts its own explicit override when needed.

The stack is local and open source, so none of it depends on the hosted AgentOS panel.

## What each tool is for

No single screen shows everything, so the pieces cover different questions.

**Agno's built-in metrics** answer "what did this LLM call cost?" and they need nothing installed. Every run already returns input/output tokens, total cost, time to first token and duration, and the runtime stores that alongside the run. Before reaching for a tool, remember this data is already in the database and can be read through the runtime's own API.

**Langfuse** is for the AI side: the prompt, the response, and the token/cost/latency breakdown of each agent execution, kept as browsable history. It earns its place when you want retention, quality evals, and heavier filtering than reading raw runs gives you.

**Prometheus** is for the operational side: request rate, HTTP status distribution, and latency percentiles over time. **Grafana** draws those and reads Loki in the same screen.

**Loki** is for logs. It collects what loguru already writes and makes it searchable, so you can spot a spike in a graph and jump straight to the lines from that moment.

**Locust** is for load testing. Note it measures client-side time, including network, which is a different number from the in-app latency Prometheus records; the two are not supposed to match exactly.

They do not replace each other. Langfuse knows nothing about CPU, and Grafana will not show you the prompt of a specific call.

## A note on `telemetry=False`

The agents are created with `telemetry=False` and that stays. This parameter controls Agno's own product analytics — anonymous usage data sent to Agno's servers — and has nothing to do with OpenTelemetry. Turning it on would not produce a single trace in Langfuse; it would only start reporting usage upstream, which is the opposite of running the stack locally.

Traces come from the `AgnoInstrumentor`, which instruments the library from outside and works regardless of that flag.

## Enabling tracing

Install the optional dependencies and point the runtime at any OTLP collector:

```bash
poetry install --extras observability
```

```bash
ENABLE_TRACING=true
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are a shortcut for the common case: they are turned into the Basic auth header Langfuse expects. For any other collector, set `OTEL_EXPORTER_OTLP_HEADERS` in the standard `key=value,key2=value2` form; it takes precedence over the Langfuse keys.

`OTEL_SERVICE_NAME` (default `acessilia`) is the name traces are grouped under.

Wiring lives in [backend/observability.py](../backend/observability.py) and is called once at API startup. If the dependencies are missing or the endpoint is unreachable, it logs a warning and the application continues.

## Enabling metrics

```bash
ENABLE_METRICS=true
```

This exposes `/metrics` in Prometheus format, outside `/api/v1` because it is a scrape endpoint rather than part of the public API contract. It reports request counts, status codes and latency, collected automatically for every route.

## Structured logs

```bash
LOG_JSON=true
```

This adds a second log file in JSON alongside the human-readable one. The plain `.log` stays exactly as it was, so reading logs in a terminal is unaffected. The JSON file exists because Loki can then filter by level or module as fields instead of running regex over text.

## Running the stack

Prometheus, Grafana, Loki and Promtail live behind a Docker profile, so the normal `docker compose up` still starts only the application:

```bash
docker compose --profile monitoring up -d
```

Promtail reads `var/logs` read-only and ships it to Loki. The application's logger is untouched by this; nothing needs to change in the code to get logs into Loki.

Configuration files are in [observability/stack/](../observability/stack/).

### Where each number shows up

Grafana at `http://localhost:3000` is the central screen: it reads both Prometheus and Loki, and boots with the datasources and the "Acessília — visão geral" dashboard already provisioned, so there is nothing to configure by hand. Login is disabled for convenience, so do not expose this port outside your machine.

| What | Stored in | Seen at |
|------|-----------|---------|
| Requests, latency, errors | Prometheus | Grafana dashboard (raw Prometheus at `:9090`) |
| Application logs | Loki | Logs panel in the same dashboard |
| Machine CPU and memory | Prometheus (node-exporter) | Same dashboard |
| LLM traces | Langfuse or another OTLP collector | That tool's own UI |
| Load test results | Locust | Its own screen at `:8089` while running |
| Tokens and cost per run | Agno's SQLite | Already recorded per run; visible through AgentOS/agent-ui |

Empty panels almost always mean the API is missing `ENABLE_METRICS=true`, or the profile is not up.

### Langfuse

Langfuse is not in the profile. Self-hosting it pulls in web, worker, Postgres, ClickHouse, Redis and MinIO, and the project recommends roughly 4 cores and 16 GiB — too heavy to sit next to the application on a development machine. Since the endpoint is a plain OTLP URL, point `OTEL_EXPORTER_OTLP_ENDPOINT` at Langfuse Cloud, at a self-hosted instance running separately, or at any other OpenTelemetry collector.

## Load testing

The Locust scenario and its knobs are in [observability/README.md](../observability/README.md); parameters live in `observability/config.py`. Running it with the monitoring profile up is the useful combination: Locust drives traffic, Grafana shows latency and error rate climbing, and the traces show what the calls cost during that window.

`observability/metricas/consultar.py` prints the same Prometheus numbers as a table, which is handy when you want a figure to paste somewhere rather than a screenshot.

## Wrapping the pipeline as an Agno Workflow

Worth knowing for later. The pipeline currently runs as plain Python orchestration, so Agno returns metrics per agent call. If it were wrapped as an Agno Workflow, metrics would also come back per run and per session, which is where "cost per document" and "duration per stage" come from without adding them up by hand.

The caveat for this codebase is that regions are processed in parallel through a fan-out, and a fan-out stage does not aggregate its own tokens; that part would still need to be summed manually.
