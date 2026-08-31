from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx


MetricKind = Literal["scalar", "vector"]
QueryState = Literal["ok", "empty", "error", "unavailable"]


@dataclass(frozen=True)
class MetricDefinition:
    label: str
    query: str
    unit: str
    key: str | None = None
    kind: MetricKind = "scalar"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "key": self.key,
            "label": self.label,
            "query": self.query,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class ServiceProbe:
    name: str
    endpoint: str
    available: bool
    status_code: int | None = None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "endpoint": self.endpoint,
            "available": self.available,
            "status_code": self.status_code,
        }
        if self.error:
            payload["error"] = self.error
        return payload


class HealthProvider(Protocol):
    name: str
    endpoint: str

    async def health(self, client: httpx.AsyncClient) -> ServiceProbe:
        ...


class MetricsProvider(Protocol):
    async def snapshot(self, client: httpx.AsyncClient) -> dict[str, Any]:
        ...

    async def realtime(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        ...

    async def timeseries(
        self,
        client: httpx.AsyncClient,
        *,
        range_seconds: int,
        step_seconds: int,
    ) -> list[dict[str, Any]]:
        ...


class LogsProvider(Protocol):
    async def entries(
        self,
        client: httpx.AsyncClient,
        *,
        search: str = "",
        limit: int | None = None,
    ) -> dict[str, Any]:
        ...
