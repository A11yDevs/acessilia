from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from observability.src.contracts import MetricDefinition
from observability.src.integrations.http import is_http_available
from observability.src.metrics_catalog import MetricsCatalog


@dataclass(frozen=True)
class PrometheusMetricsProvider:
    base_url: str
    catalog: MetricsCatalog

    async def snapshot(self, client: httpx.AsyncClient) -> dict[str, Any]:
        available = await is_http_available(client, self.base_url, "/-/ready")
        if not available:
            return {"available": False, "groups": self._empty_groups()}

        return {
            "available": True,
            "groups": await self.metric_groups(client),
        }

    async def metric_groups(
        self,
        client: httpx.AsyncClient,
    ) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for name, definitions in self.catalog.groups.items():
            groups[name] = await self._read_metric_definitions(client, definitions)
        return groups

    async def realtime(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        if not await is_http_available(client, self.base_url, "/-/ready"):
            return [_empty_metric(definition) for definition in self.catalog.realtime]
        return await self._read_metric_definitions(client, self.catalog.realtime)

    async def timeseries(
        self,
        client: httpx.AsyncClient,
        *,
        range_seconds: int,
        step_seconds: int,
    ) -> list[dict[str, Any]]:
        if not await is_http_available(client, self.base_url, "/-/ready"):
            return [
                _series_payload(definition, None)
                for definition in self.catalog.timeseries
            ]

        end = time.time()
        start = end - range_seconds
        results = await asyncio.gather(
            *[
                self._range_result(
                    client,
                    definition.query,
                    start=start,
                    end=end,
                    step=step_seconds,
                )
                for definition in self.catalog.timeseries
            ]
        )
        return [
            _series_payload(definition, result)
            for definition, result in zip(self.catalog.timeseries, results, strict=True)
        ]

    async def _read_metric_definitions(
        self,
        client: httpx.AsyncClient,
        definitions: tuple[MetricDefinition, ...],
    ) -> list[dict[str, Any]]:
        return list(
            await asyncio.gather(
                *[self._metric(client, definition) for definition in definitions]
            )
        )

    def _empty_groups(self) -> dict[str, list[dict[str, Any]]]:
        return {
            name: [_empty_metric(definition) for definition in definitions]
            for name, definitions in self.catalog.groups.items()
        }

    async def _metric(
        self,
        client: httpx.AsyncClient,
        definition: MetricDefinition,
    ) -> dict[str, Any]:
        if definition.kind == "vector":
            items = await self._vector(client, definition.query)
            return {
                "key": definition.key,
                "label": definition.label,
                "value": None,
                "unit": definition.unit,
                "items": items,
            }

        value = await self._scalar(client, definition.query)
        return {
            "key": definition.key,
            "label": definition.label,
            "value": value,
            "unit": definition.unit,
            "items": [],
        }

    async def _scalar(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> float | None:
        result = await self._result(client, query)
        if not result:
            return None
        try:
            return float(result[0]["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    async def _vector(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> list[dict[str, Any]]:
        result = await self._result(client, query)
        items: list[dict[str, Any]] = []
        for row in result or []:
            metric = row.get("metric", {})
            label = _prometheus_label(metric)
            try:
                value = float(row["value"][1])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            items.append({"label": label, "value": value, "metric": metric})
        return items

    async def _result(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> list[dict[str, Any]] | None:
        try:
            response = await client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
            )
            response.raise_for_status()
            return response.json().get("data", {}).get("result", [])
        except Exception:
            return None

    async def _range_result(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        start: float,
        end: float,
        step: int,
    ) -> list[dict[str, Any]] | None:
        try:
            response = await client.get(
                f"{self.base_url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": f"{start:.3f}",
                    "end": f"{end:.3f}",
                    "step": str(step),
                },
            )
            response.raise_for_status()
            return response.json().get("data", {}).get("result", [])
        except Exception:
            return None


def _series_payload(
    definition: MetricDefinition,
    result: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    points: list[dict[str, float]] = []
    if result:
        for timestamp, raw_value in result[0].get("values", []):
            try:
                points.append({"time": float(timestamp), "value": float(raw_value)})
            except (TypeError, ValueError):
                continue
    return {
        "key": definition.key,
        "label": definition.label,
        "unit": definition.unit,
        "points": points,
    }


def _empty_metric(definition: MetricDefinition) -> dict[str, Any]:
    return {
        "key": definition.key,
        "label": definition.label,
        "value": None,
        "unit": definition.unit,
        "items": [],
    }


def _prometheus_label(metric: dict[str, Any]) -> str:
    preferred = [
        "agent",
        "token_type",
        "content_type",
        "model_provider",
        "model",
        "status",
        "stage",
        "format",
        "instance",
    ]
    parts = [str(metric[key]) for key in preferred if metric.get(key)]
    return " / ".join(parts) if parts else "total"
