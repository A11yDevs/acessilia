from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from observability.src.storage.sqlite import DEFAULT_DB_PATH


def env_url(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ObservabilitySettings:
    project_name: str
    metric_prefix: str
    prometheus_api_job: str
    loki_query: str
    api_url: str
    prometheus_url: str
    loki_url: str
    langfuse_url: str
    tempo_url: str
    locust_url: str
    agno_os_url: str
    agno_os_security_key: str
    db_path: Path
    store_reasoning: bool
    api_health_path: str
    api_stats_path: str
    api_history_path: str
    public_links: dict[str, str]
    frontend_tracing_enabled: bool
    otel_service_name: str
    otel_exporter_otlp_endpoint: str
    otel_exporter_otlp_headers: str

    @classmethod
    def from_env(cls) -> "ObservabilitySettings":
        project_name = os.getenv("OBSERVABILITY_PROJECT_NAME", "Acessilia").strip()
        metric_prefix = os.getenv("OBSERVABILITY_METRIC_PREFIX", "acessilia").strip()
        prometheus_api_job = os.getenv(
            "OBSERVABILITY_PROMETHEUS_API_JOB",
            f"{metric_prefix}-api",
        ).strip()
        loki_query = os.getenv(
            "OBSERVABILITY_LOKI_QUERY",
            f'{{job="{metric_prefix}"}}',
        ).strip()

        api_url = env_url("ACESSILIA_API_URL", "http://localhost:8000")
        prometheus_url = env_url("PROMETHEUS_URL", "http://localhost:9090")
        loki_url = env_url("LOKI_URL", "http://localhost:3100")
        langfuse_url = env_url("LANGFUSE_URL", "http://localhost:3001")
        tempo_url = env_url("TEMPO_URL", "http://localhost:3200")
        locust_url = env_url("LOCUST_URL", "http://localhost:8089")
        agno_os_url = env_url("AGNO_OS_URL", "http://localhost:7777")

        db_path = Path(
            os.getenv("OBSERVABILITY_DB_PATH", str(DEFAULT_DB_PATH))
        ).expanduser()

        public_links = {
            "api": env_url("PUBLIC_ACESSILIA_API_URL", "http://localhost:8000"),
            "grafana": env_url("PUBLIC_GRAFANA_URL", "http://localhost:3000"),
            "prometheus": env_url("PUBLIC_PROMETHEUS_URL", "http://localhost:9090"),
            "loki": env_url("PUBLIC_LOKI_URL", "http://localhost:3100"),
            "langfuse": env_url("PUBLIC_LANGFUSE_URL", "http://localhost:3001"),
            "tempo": env_url("PUBLIC_TEMPO_URL", "http://localhost:3200"),
            "locust": env_url("PUBLIC_LOCUST_URL", "http://localhost:8089"),
            "agno": "/agno",
        }

        return cls(
            project_name=project_name or "Observability",
            metric_prefix=metric_prefix or "app",
            prometheus_api_job=prometheus_api_job or "app-api",
            loki_query=loki_query or '{job="app"}',
            api_url=api_url,
            prometheus_url=prometheus_url,
            loki_url=loki_url,
            langfuse_url=langfuse_url,
            tempo_url=tempo_url,
            locust_url=locust_url,
            agno_os_url=agno_os_url,
            agno_os_security_key=os.getenv("AGNO_OS_SECURITY_KEY", "").strip(),
            db_path=db_path,
            store_reasoning=env_flag("AGNO_CONSOLE_STORE_REASONING", False),
            api_health_path=os.getenv("OBSERVABILITY_API_HEALTH_PATH", "/api/v1/health"),
            api_stats_path=os.getenv("OBSERVABILITY_API_STATS_PATH", "/api/v1/stats"),
            api_history_path=os.getenv(
                "OBSERVABILITY_API_HISTORY_PATH",
                "/api/v1/history?limit=20",
            ),
            public_links=public_links,
            frontend_tracing_enabled=env_flag("OBSERVABILITY_FRONTEND_TRACING", False),
            otel_service_name=os.getenv(
                "OTEL_SERVICE_NAME",
                f"{metric_prefix}-observability",
            ).strip(),
            otel_exporter_otlp_endpoint=env_url(
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "",
            ),
            otel_exporter_otlp_headers=os.getenv(
                "OTEL_EXPORTER_OTLP_HEADERS",
                "",
            ).strip(),
        )
