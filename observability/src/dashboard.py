from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from observability.src.integrations.agno import AgnoClient
from observability.src.integrations.http import service_probe
from observability.src.integrations.loki import LokiLogsProvider
from observability.src.integrations.project_api import ProjectApiClient
from observability.src.integrations.prometheus import PrometheusMetricsProvider
from observability.src.settings import ObservabilitySettings


@dataclass(frozen=True)
class DashboardService:
    settings: ObservabilitySettings
    project_api: ProjectApiClient
    metrics_provider: PrometheusMetricsProvider
    logs_provider: LokiLogsProvider

    async def snapshot(self, client: httpx.AsyncClient) -> dict[str, Any]:
        agno = AgnoClient(
            self.settings.agno_os_url,
            self.settings.agno_os_security_key,
        )
        (
            api,
            metrics,
            logs,
            langfuse,
            tempo,
            locust,
            collector,
            agno_status,
        ) = await asyncio.gather(
            self.project_api.snapshot(client),
            self.metrics_provider.snapshot(client),
            self.logs_provider.entries(client),
            service_probe(
                client,
                name="langfuse",
                base_url=self.settings.langfuse_url,
                path="/api/public/health",
            ),
            service_probe(
                client,
                name="tempo",
                base_url=self.settings.tempo_url,
                path="/ready",
            ),
            service_probe(
                client,
                name="locust",
                base_url=self.settings.locust_url,
            ),
            service_probe(
                client,
                name="otel",
                base_url=self.settings.otel_collector_url,
            ),
            agno.health(client),
        )

        api_available = api["health"] is not None
        service_details = {
            "api": _service_detail(
                name="api",
                endpoint=self.settings.api_url,
                available=api_available,
            ),
            "prometheus": _with_state(metrics["probe"]),
            "loki": _with_state(
                logs["probe"],
                degraded=logs["available"] and not logs["query_available"],
                error=logs.get("error", ""),
            ),
            "langfuse": _with_state(langfuse.as_dict()),
            "tempo": _with_state(tempo.as_dict()),
            "locust": _with_state(locust.as_dict()),
            "otel": _with_state(collector.as_dict()),
            "agno": _with_state({"name": "agno", **agno_status}),
        }
        services = {
            name: bool(detail["available"])
            for name, detail in service_details.items()
        }

        metric_states = [
            metric.get("state", "empty")
            for group in metrics["groups"].values()
            for metric in group
        ]
        sources = {
            "metrics": {
                "available": metrics["available"],
                "state": _source_state(metrics["available"], metric_states),
                "query_errors": metric_states.count("error"),
                "series_with_data": metric_states.count("ok"),
            },
            "logs": {
                "available": logs["available"],
                "state": (
                    "offline"
                    if not logs["available"]
                    else "online"
                    if logs["query_available"]
                    else "degraded"
                ),
                "query_available": logs["query_available"],
                "entries": len(logs["entries"]),
                "error": logs.get("error", ""),
            },
        }

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "services": services,
            "service_details": service_details,
            "sources": sources,
            "api": api,
            "metrics": metrics["groups"],
            "logs": logs["entries"],
            "links": self.settings.public_links,
        }


def _service_detail(
    *,
    name: str,
    endpoint: str,
    available: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "endpoint": endpoint,
        "available": available,
        "status_code": None,
        "state": "online" if available else "offline",
    }


def _with_state(
    detail: dict[str, Any],
    *,
    degraded: bool = False,
    error: str = "",
) -> dict[str, Any]:
    normalized = dict(detail)
    available = bool(normalized.get("available"))
    normalized["state"] = (
        "degraded" if available and degraded else "online" if available else "offline"
    )
    if error:
        normalized["error"] = error
    return normalized


def _source_state(available: bool, states: list[str]) -> str:
    if not available:
        return "offline"
    if "error" in states:
        return "degraded"
    if "ok" not in states:
        return "empty"
    return "online"
