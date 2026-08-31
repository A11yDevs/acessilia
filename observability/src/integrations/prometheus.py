from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from observability.src.contracts import MetricDefinition, QueryState, ServiceProbe
from observability.src.metrics_catalog import MetricsCatalog


@dataclass(frozen=True)
class PrometheusMetricsProvider:
    base_url: str
    catalog: MetricsCatalog

    async def probe(self, client: httpx.AsyncClient) -> ServiceProbe:
        try:
            response = await client.get(f"{self.base_url}/-/ready")
            return ServiceProbe(
                name="prometheus",
                endpoint=self.base_url,
                available=response.is_success,
                status_code=response.status_code,
            )
        except httpx.HTTPError as exc:
            return ServiceProbe(
                name="prometheus",
                endpoint=self.base_url,
                available=False,
                error=str(exc),
            )

    async def snapshot(self, client: httpx.AsyncClient) -> dict[str, Any]:
        probe = await self.probe(client)
        if not probe.available:
            return {
                "available": False,
                "probe": probe.as_dict(),
                "groups": self._empty_groups("unavailable"),
            }

        return {
            "available": True,
            "probe": probe.as_dict(),
            "groups": await self.metric_groups(client),
        }

    async def metric_groups(
        self,
        client: httpx.AsyncClient,
    ) -> dict[str, list[dict[str, Any]]]:
        names = list(self.catalog.groups)
        results = await asyncio.gather(
            *[
                self._read_metric_definitions(client, self.catalog.groups[name])
                for name in names
            ]
        )
        return dict(zip(names, results, strict=True))

    async def realtime(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        if not (await self.probe(client)).available:
            return [
                _empty_metric(definition, "unavailable")
                for definition in self.catalog.realtime
            ]
        return await self._read_metric_definitions(client, self.catalog.realtime)

    async def timeseries(
        self,
        client: httpx.AsyncClient,
        *,
        range_seconds: int,
        step_seconds: int,
    ) -> list[dict[str, Any]]:
        if not (await self.probe(client)).available:
            return [
                _series_payload(definition, None, "unavailable")
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
            _series_payload(definition, result, state, error)
            for definition, (result, state, error) in zip(
                self.catalog.timeseries,
                results,
                strict=True,
            )
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

    def _empty_groups(
        self,
        state: QueryState,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            name: [_empty_metric(definition, state) for definition in definitions]
            for name, definitions in self.catalog.groups.items()
        }

    async def _metric(
        self,
        client: httpx.AsyncClient,
        definition: MetricDefinition,
    ) -> dict[str, Any]:
        if definition.kind == "vector":
            items, state, error = await self._vector(client, definition.query)
            payload = {
                "key": definition.key,
                "label": definition.label,
                "value": None,
                "unit": definition.unit,
                "items": items,
                "state": state,
            }
            if error:
                payload["error"] = error
            return payload

        value, state, error = await self._scalar(client, definition.query)
        payload = {
            "key": definition.key,
            "label": definition.label,
            "value": value,
            "unit": definition.unit,
            "items": [],
            "state": state,
        }
        if error:
            payload["error"] = error
        return payload

    async def _scalar(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> tuple[float | None, QueryState, str]:
        result, error = await self._result(client, query)
        if result is None:
            return None, "error", error
        if not result:
            return None, "empty", ""
        try:
            return float(result[0]["value"][1]), "ok", ""
        except (KeyError, IndexError, TypeError, ValueError):
            return None, "error", "Resposta escalar inválida do Prometheus."

    async def _vector(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> tuple[list[dict[str, Any]], QueryState, str]:
        result, error = await self._result(client, query)
        if result is None:
            return [], "error", error
        items: list[dict[str, Any]] = []
        for row in result:
            metric = row.get("metric", {})
            label = _prometheus_label(metric)
            try:
                value = float(row["value"][1])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            items.append({"label": label, "value": value, "metric": metric})
        return items, ("ok" if items else "empty"), ""

    async def _result(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> tuple[list[dict[str, Any]] | None, str]:
        try:
            response = await client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "error":
                return None, str(payload.get("error") or "Consulta Prometheus falhou.")
            return payload.get("data", {}).get("result", []), ""
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return None, str(exc)

    async def _range_result(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        start: float,
        end: float,
        step: int,
    ) -> tuple[list[dict[str, Any]] | None, QueryState, str]:
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
            payload = response.json()
            if payload.get("status") == "error":
                return None, "error", str(
                    payload.get("error") or "Consulta Prometheus falhou."
                )
            result = payload.get("data", {}).get("result", [])
            return result, ("ok" if result else "empty"), ""
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return None, "error", str(exc)


def _series_payload(
    definition: MetricDefinition,
    result: list[dict[str, Any]] | None,
    state: QueryState,
    error: str = "",
) -> dict[str, Any]:
    points: list[dict[str, float]] = []
    if result:
        for timestamp, raw_value in result[0].get("values", []):
            try:
                points.append({"time": float(timestamp), "value": float(raw_value)})
            except (TypeError, ValueError):
                continue
    payload = {
        "key": definition.key,
        "label": definition.label,
        "unit": definition.unit,
        "points": points,
        "state": state if points or state != "ok" else "empty",
    }
    if error:
        payload["error"] = error
    return payload


def _empty_metric(
    definition: MetricDefinition,
    state: QueryState = "empty",
) -> dict[str, Any]:
    return {
        "key": definition.key,
        "label": definition.label,
        "value": None,
        "unit": definition.unit,
        "items": [],
        "state": state,
    }


def _prometheus_label(metric: dict[str, Any]) -> str:
    preferred = [
        "agent",
        "entity_id",
        "entity_type",
        "tool_name",
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
