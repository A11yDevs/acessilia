from __future__ import annotations

from dataclasses import dataclass

from observability.src.contracts import MetricDefinition


DEFAULT_INTERNAL_HANDLER_RE = "/metrics|/api/v1/health|/api/v1/stats|/api/v1/history"
HTTP_4XX_RE = "4..|4xx"
HTTP_5XX_RE = "5..|5xx"


@dataclass(frozen=True)
class MetricsCatalog:
    realtime: tuple[MetricDefinition, ...]
    timeseries: tuple[MetricDefinition, ...]
    groups: dict[str, tuple[MetricDefinition, ...]]


def build_metrics_catalog(
    *,
    metric_prefix: str = "acessilia",
    api_job_name: str = "acessilia-api",
    observability_job_name: str = "acessilia-observability",
    internal_handler_re: str = DEFAULT_INTERNAL_HANDLER_RE,
) -> MetricsCatalog:
    def selector(extra: str = "") -> str:
        extra = f",{extra}" if extra else ""
        return f'{{job="{api_job_name}"{extra}}}'

    def zero(query: str) -> str:
        return f"(({query}) or vector(0))"

    def metric(name: str) -> str:
        prefix = metric_prefix.strip().rstrip("_") or "app"
        return f"{prefix}_{name}"

    def traffic_rate(extra: str = "", window: str = "30s") -> str:
        return zero(f"sum(rate(http_requests_total{selector(extra)}[{window}]))")

    user_traffic_filter = f'handler!~"{internal_handler_re}"'
    internal_traffic_filter = f'handler=~"{internal_handler_re}"'
    http_4xx_user_filter = f'{user_traffic_filter},status=~"{HTTP_4XX_RE}"'
    http_5xx_user_filter = f'{user_traffic_filter},status=~"{HTTP_5XX_RE}"'
    http_error_user_filter = (
        f'{user_traffic_filter},status=~"{HTTP_4XX_RE}|{HTTP_5XX_RE}"'
    )

    req_user = traffic_rate(user_traffic_filter)
    req_internal = traffic_rate(internal_traffic_filter)
    req_total = traffic_rate()
    http_user_denominator = zero(
        f"sum(rate(http_requests_total{selector(user_traffic_filter)}[5m]))"
    )
    http_4xx_user = (
        f"({traffic_rate(http_4xx_user_filter, '5m')} "
        f"/ clamp_min({http_user_denominator}, 0.001)) * 100"
    )
    http_5xx_user = (
        f"({traffic_rate(http_5xx_user_filter, '5m')} "
        f"/ clamp_min({http_user_denominator}, 0.001)) * 100"
    )
    http_error_user = (
        f"({traffic_rate(http_error_user_filter, '5m')} "
        f"/ clamp_min({http_user_denominator}, 0.001)) * 100"
    )
    p95_user = (
        "histogram_quantile(0.95, sum by (le) "
        f"(rate(http_request_duration_seconds_bucket{selector(user_traffic_filter)}[5m])))"
    )
    cpu_query = zero('100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)')
    ram_query = zero(
        "avg((1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100)"
    )
    disk_root_query = zero(
        'max(100 * (1 - (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs|proc|sysfs|devtmpfs"} '
        '/ node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs|proc|sysfs|devtmpfs"})))'
    )
    net_rx_query = zero(
        'sum(rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*|br-.*|flannel.*|cali.*"}[1m]))'
    )
    net_tx_query = zero(
        'sum(rate(node_network_transmit_bytes_total{device!~"lo|veth.*|docker.*|br-.*|flannel.*|cali.*"}[1m]))'
    )
    gpu_util_query = "avg(DCGM_FI_DEV_GPU_UTIL)"
    gpu_vram_query = (
        "sum(DCGM_FI_DEV_FB_USED) / clamp_min(sum(DCGM_FI_DEV_FB_TOTAL), 1) * 100"
    )
    gpu_watts_query = "avg(DCGM_FI_DEV_POWER_USAGE)"
    gpu_temp_query = "avg(DCGM_FI_DEV_GPU_TEMP)"
    queue_query = zero(metric("queue_size"))
    jobs_active_query = zero(f"sum({metric('jobs_active')})")
    jobs_done_rate_query = zero(
        f'sum(rate({metric("jobs_total")}{{status="done"}}[1m])) * 60'
    )
    jobs_error_rate_query = zero(
        f'sum(rate({metric("jobs_total")}{{status="error"}}[1m])) * 60'
    )
    pipeline_errors_rate_query = zero(
        f"sum(rate({metric('pipeline_errors_total')}[1m])) * 60"
    )
    conversion_avg_query = zero(
        f"sum(rate({metric('conversion_duration_seconds_sum')}[5m])) "
        f"/ clamp_min(sum(rate({metric('conversion_duration_seconds_count')}[5m])), 1)"
    )
    exports_rate_query = zero(f"sum(rate({metric('exports_total')}[1m])) * 60")
    output_bytes_rate_query = zero(f"sum(rate({metric('output_bytes_sum')}[1m]))")
    llm_calls_per_min_query = zero(f"sum(rate({metric('llm_calls_total')}[1m])) * 60")
    llm_failures_per_min_query = zero(
        f"sum(rate({metric('llm_failures_total')}[1m])) * 60"
    )
    llm_duration_avg_query = zero(
        f"sum(rate({metric('llm_duration_seconds_sum')}[5m])) "
        f"/ clamp_min(sum(rate({metric('llm_duration_seconds_count')}[5m])), 1)"
    )
    llm_ttft_avg_query = zero(
        f"sum(rate({metric('llm_time_to_first_token_seconds_sum')}[5m])) "
        f"/ clamp_min(sum(rate({metric('llm_time_to_first_token_seconds_count')}[5m])), 1)"
    )
    llm_total_tokens_rate_query = zero(
        f'sum(rate({metric("llm_tokens_total")}{{token_type="total"}}[1m]))'
    )
    llm_input_tokens_rate_query = zero(
        f'sum(rate({metric("llm_tokens_total")}{{token_type="input"}}[1m]))'
    )
    llm_output_tokens_rate_query = zero(
        f'sum(rate({metric("llm_tokens_total")}{{token_type="output"}}[1m]))'
    )
    llm_reasoning_tokens_rate_query = zero(
        f'sum(rate({metric("llm_tokens_total")}{{token_type="reasoning"}}[1m]))'
    )
    llm_cache_read_tokens_rate_query = zero(
        f'sum(rate({metric("llm_tokens_total")}{{token_type="cache_read"}}[1m]))'
    )
    llm_cache_write_tokens_rate_query = zero(
        f'sum(rate({metric("llm_tokens_total")}{{token_type="cache_write"}}[1m]))'
    )
    llm_cost_per_min_query = zero(f"sum(rate({metric('llm_cost_total')}[5m])) * 60")
    agno_calls_per_min_query = zero(
        f"sum(rate({metric('agno_chat_calls_total')}[1m])) * 60"
    )
    agno_failures_per_min_query = zero(
        f"sum(rate({metric('agno_chat_failures_total')}[1m])) * 60"
    )
    agno_duration_avg_query = zero(
        f"sum(rate({metric('agno_chat_duration_seconds_sum')}[5m])) "
        f"/ clamp_min(sum(rate({metric('agno_chat_duration_seconds_count')}[5m])), 1)"
    )
    agno_ttft_avg_query = zero(
        f"sum(rate({metric('agno_chat_ttft_seconds_sum')}[5m])) "
        f"/ clamp_min(sum(rate({metric('agno_chat_ttft_seconds_count')}[5m])), 1)"
    )
    agno_input_tokens_rate_query = zero(
        f'sum(rate({metric("agno_chat_tokens_total")}{{token_type="input"}}[1m]))'
    )
    agno_output_tokens_rate_query = zero(
        f'sum(rate({metric("agno_chat_tokens_total")}{{token_type="output"}}[1m]))'
    )
    agno_reasoning_tokens_rate_query = zero(
        f'sum(rate({metric("agno_chat_tokens_total")}{{token_type="reasoning"}}[1m]))'
    )
    agno_cost_per_min_query = zero(
        f"sum(rate({metric('agno_chat_cost_total')}[5m])) * 60"
    )
    agno_tool_calls_per_min_query = zero(
        f"sum(rate({metric('agno_chat_tool_calls_total')}[1m])) * 60"
    )

    realtime = (
        MetricDefinition("Req/s usuários", req_user, "rps", key="req_user"),
        MetricDefinition("Req/s interno", req_internal, "rps", key="req_internal"),
        MetricDefinition("Req/s total", req_total, "rps", key="req_total"),
        MetricDefinition("HTTP 4xx %", http_4xx_user, "percent", key="http_4xx"),
        MetricDefinition("HTTP 5xx %", http_5xx_user, "percent", key="http_5xx"),
        MetricDefinition("Fila", queue_query, "count", key="queue"),
        MetricDefinition("Jobs ativos", jobs_active_query, "count", key="jobs_active"),
        MetricDefinition("CPU", cpu_query, "percent", key="cpu"),
        MetricDefinition("RAM", ram_query, "percent", key="ram"),
        MetricDefinition(
            "LLM chamadas/min",
            llm_calls_per_min_query,
            "per_minute",
            key="llm_calls_per_min",
        ),
        MetricDefinition(
            "LLM tokens/s",
            llm_total_tokens_rate_query,
            "tokens_per_second",
            key="llm_total_tokens_rate",
        ),
        MetricDefinition("LLM TTFT", llm_ttft_avg_query, "seconds", key="llm_ttft_avg"),
        MetricDefinition(
            "Runs Agno/min",
            agno_calls_per_min_query,
            "per_minute",
            key="agno_calls_per_min",
        ),
    )

    timeseries = (
        *realtime,
        MetricDefinition("Disco /", disk_root_query, "percent", key="disk_root"),
        MetricDefinition("Rede entrada", net_rx_query, "bytes_per_second", key="net_rx"),
        MetricDefinition("Rede saída", net_tx_query, "bytes_per_second", key="net_tx"),
        MetricDefinition("Jobs ok/min", jobs_done_rate_query, "per_minute", key="jobs_done_per_min"),
        MetricDefinition("Jobs erro/min", jobs_error_rate_query, "per_minute", key="jobs_error_per_min"),
        MetricDefinition("Erros pipeline/min", pipeline_errors_rate_query, "per_minute", key="pipeline_errors_per_min"),
        MetricDefinition("Conversão média", conversion_avg_query, "seconds", key="conversion_avg"),
        MetricDefinition("Exportações/min", exports_rate_query, "per_minute", key="exports_per_min"),
        MetricDefinition("Outputs/s", output_bytes_rate_query, "bytes_per_second", key="output_bytes_rate"),
        MetricDefinition("LLM falhas/min", llm_failures_per_min_query, "per_minute", key="llm_failures_per_min"),
        MetricDefinition("LLM duração", llm_duration_avg_query, "seconds", key="llm_duration_avg"),
        MetricDefinition("Input tokens/s", llm_input_tokens_rate_query, "tokens_per_second", key="llm_input_tokens_rate"),
        MetricDefinition("Output tokens/s", llm_output_tokens_rate_query, "tokens_per_second", key="llm_output_tokens_rate"),
        MetricDefinition("Reasoning tokens/s", llm_reasoning_tokens_rate_query, "tokens_per_second", key="llm_reasoning_tokens_rate"),
        MetricDefinition("Cache read tokens/s", llm_cache_read_tokens_rate_query, "tokens_per_second", key="llm_cache_read_tokens_rate"),
        MetricDefinition("Cache write tokens/s", llm_cache_write_tokens_rate_query, "tokens_per_second", key="llm_cache_write_tokens_rate"),
        MetricDefinition("LLM custo/min", llm_cost_per_min_query, "currency_per_minute", key="llm_cost_per_min"),
        MetricDefinition("Runs Agno/min", agno_calls_per_min_query, "per_minute", key="agno_calls_per_min"),
        MetricDefinition("Falhas Agno/min", agno_failures_per_min_query, "per_minute", key="agno_failures_per_min"),
        MetricDefinition("Duração Agno", agno_duration_avg_query, "seconds", key="agno_duration_avg"),
        MetricDefinition("TTFT Agno", agno_ttft_avg_query, "seconds", key="agno_ttft_avg"),
        MetricDefinition("Input Agno tokens/s", agno_input_tokens_rate_query, "tokens_per_second", key="agno_input_tokens_rate"),
        MetricDefinition("Output Agno tokens/s", agno_output_tokens_rate_query, "tokens_per_second", key="agno_output_tokens_rate"),
        MetricDefinition("Reasoning Agno tokens/s", agno_reasoning_tokens_rate_query, "tokens_per_second", key="agno_reasoning_tokens_rate"),
        MetricDefinition("Custo Agno/min", agno_cost_per_min_query, "currency_per_minute", key="agno_cost_per_min"),
        MetricDefinition("Tools Agno/min", agno_tool_calls_per_min_query, "per_minute", key="agno_tool_calls_per_min"),
        MetricDefinition("GPU uso", gpu_util_query, "percent", key="gpu_util"),
        MetricDefinition("GPU VRAM", gpu_vram_query, "percent", key="gpu_vram"),
        MetricDefinition("GPU watts", gpu_watts_query, "watts", key="gpu_watts"),
        MetricDefinition("GPU temp.", gpu_temp_query, "celsius", key="gpu_temp"),
    )

    groups = {
        "overview": (
            MetricDefinition("API up", f'up{{job="{api_job_name}"}}', "state"),
            MetricDefinition("Req/s usuários", req_user, "rps"),
            MetricDefinition("Req/s interno", req_internal, "rps"),
            MetricDefinition("Req/s total", req_total, "rps"),
            MetricDefinition("Erro HTTP usuário %", http_error_user, "percent"),
            MetricDefinition("HTTP 4xx usuário %", http_4xx_user, "percent"),
            MetricDefinition("HTTP 5xx usuário %", http_5xx_user, "percent"),
            MetricDefinition("p95 usuário", p95_user, "seconds"),
        ),
        "pipeline": (
            MetricDefinition("Fila", queue_query, "count"),
            MetricDefinition("Jobs ativos", jobs_active_query, "count"),
            MetricDefinition(
                "Jobs por status",
                f"sum by (status) ({metric('jobs_total')})",
                "count",
                kind="vector",
            ),
            MetricDefinition(
                "Erros por etapa",
                f"sum by (stage) ({metric('pipeline_errors_total')})",
                "count",
                kind="vector",
            ),
            MetricDefinition("Jobs ok/min", jobs_done_rate_query, "per_minute"),
            MetricDefinition("Jobs erro/min", jobs_error_rate_query, "per_minute"),
            MetricDefinition("Erros pipeline/min", pipeline_errors_rate_query, "per_minute"),
        ),
        "detailed": (
            MetricDefinition("Duração média", conversion_avg_query, "seconds"),
            MetricDefinition("Exportações/min", exports_rate_query, "per_minute"),
            MetricDefinition("Outputs/s", output_bytes_rate_query, "bytes_per_second"),
            MetricDefinition(
                "Duração média histórica",
                f"sum({metric('conversion_duration_seconds_sum')}) "
                f"/ clamp_min(sum({metric('conversion_duration_seconds_count')}), 1)",
                "seconds",
            ),
            MetricDefinition(
                "Exportações por formato",
                f"sum by (format) ({metric('exports_total')})",
                "count",
                kind="vector",
            ),
            MetricDefinition(
                "Bytes por formato",
                f"sum by (format) ({metric('output_bytes_sum')})",
                "bytes",
                kind="vector",
            ),
        ),
        "infra": (
            MetricDefinition("CPU", cpu_query, "percent"),
            MetricDefinition("RAM", ram_query, "percent"),
            MetricDefinition("Disco /", disk_root_query, "percent"),
            MetricDefinition("Rede entrada", net_rx_query, "bytes_per_second"),
            MetricDefinition("Rede saída", net_tx_query, "bytes_per_second"),
            MetricDefinition("Prometheus targets", "sum(up)", "count"),
            MetricDefinition("Alloy up", 'up{job="alloy"}', "state"),
            MetricDefinition(
                "Painel de observabilidade up",
                f'up{{job="{observability_job_name}"}}',
                "state",
            ),
            MetricDefinition("GPU uso", gpu_util_query, "percent"),
            MetricDefinition("GPU VRAM", gpu_vram_query, "percent"),
            MetricDefinition("GPU watts", gpu_watts_query, "watts"),
            MetricDefinition("GPU temp.", gpu_temp_query, "celsius"),
        ),
        "llm": (
            MetricDefinition("Chamadas/min", llm_calls_per_min_query, "per_minute"),
            MetricDefinition("Falhas/min", llm_failures_per_min_query, "per_minute"),
            MetricDefinition("Tokens/s", llm_total_tokens_rate_query, "tokens_per_second"),
            MetricDefinition("TTFT médio", llm_ttft_avg_query, "seconds"),
            MetricDefinition("Duração média", llm_duration_avg_query, "seconds"),
            MetricDefinition("Custo/min", llm_cost_per_min_query, "currency_per_minute"),
            MetricDefinition(
                "Chamadas por agente",
                f"sum by (agent) ({metric('llm_calls_total')})",
                "count",
                kind="vector",
            ),
            MetricDefinition(
                "Falhas por agente",
                f"sum by (agent) ({metric('llm_failures_total')})",
                "count",
                kind="vector",
            ),
            MetricDefinition(
                "Duração média por agente",
                f"sum by (agent) ({metric('llm_duration_seconds_sum')}) "
                f"/ clamp_min(sum by (agent) ({metric('llm_duration_seconds_count')}), 1)",
                "seconds",
                kind="vector",
            ),
            MetricDefinition(
                "TTFT por modelo",
                f"sum by (agent, model_provider, model) "
                f"(rate({metric('llm_time_to_first_token_seconds_sum')}[5m])) "
                f"/ clamp_min(sum by (agent, model_provider, model) "
                f"(rate({metric('llm_time_to_first_token_seconds_count')}[5m])), 1)",
                "seconds",
                kind="vector",
            ),
            MetricDefinition(
                "Tokens por tipo",
                f"sum by (token_type) ({metric('llm_tokens_total')})",
                "tokens",
                kind="vector",
            ),
            MetricDefinition(
                "Tokens por agente/tipo",
                f"sum by (agent, token_type) ({metric('llm_tokens_total')})",
                "tokens",
                kind="vector",
            ),
            MetricDefinition(
                "Custo por agente",
                f"sum by (agent, model_provider, model) ({metric('llm_cost_total')})",
                "currency",
                kind="vector",
            ),
            MetricDefinition(
                "Prompt/resposta médios",
                f"sum by (agent, content_type) ({metric('llm_content_chars_sum')}) "
                f"/ clamp_min(sum by (agent, content_type) "
                f"({metric('llm_content_chars_count')}), 1)",
                "chars",
                kind="vector",
            ),
            MetricDefinition(
                "Modelos observados",
                metric("llm_model_info"),
                "state",
                kind="vector",
            ),
            MetricDefinition("Runs diretos Agno/min", agno_calls_per_min_query, "per_minute"),
            MetricDefinition("Falhas diretas Agno/min", agno_failures_per_min_query, "per_minute"),
            MetricDefinition("Duração direta Agno", agno_duration_avg_query, "seconds"),
            MetricDefinition("TTFT direto Agno", agno_ttft_avg_query, "seconds"),
            MetricDefinition("Custo direto Agno/min", agno_cost_per_min_query, "currency_per_minute"),
            MetricDefinition(
                "Runs diretos por entidade",
                f"sum by (entity_type, entity_id, status) ({metric('agno_chat_calls_total')})",
                "count",
                kind="vector",
            ),
            MetricDefinition(
                "Tokens diretos por entidade/tipo",
                f"sum by (entity_id, token_type) ({metric('agno_chat_tokens_total')})",
                "tokens",
                kind="vector",
            ),
            MetricDefinition(
                "Ferramentas diretas por entidade",
                f"sum by (entity_id, tool_name, status) ({metric('agno_chat_tool_calls_total')})",
                "count",
                kind="vector",
            ),
        ),
    }

    return MetricsCatalog(realtime=realtime, timeseries=timeseries, groups=groups)
