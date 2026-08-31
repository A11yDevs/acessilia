from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class AgnoEntity:
    id: str
    name: str
    type: str
    db_id: str
    model: dict[str, Any]


class AgnoClient:
    def __init__(self, base_url: str, auth_token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token.strip()

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    async def health(self, client: httpx.AsyncClient) -> dict[str, Any]:
        try:
            response = await client.get(
                f"{self.base_url}/health",
                headers=self.headers(),
            )
            return {
                "available": response.status_code == 200,
                "status_code": response.status_code,
                "endpoint": self.base_url,
            }
        except httpx.HTTPError as exc:
            return {
                "available": False,
                "status_code": None,
                "endpoint": self.base_url,
                "error": str(exc),
            }

    async def entities(self, client: httpx.AsyncClient) -> dict[str, Any]:
        agents, teams = await self._read_entities(client)
        return {
            "agents": agents,
            "teams": teams,
            "workflows": [],
            "step_functions": [],
        }

    async def _read_entities(
        self,
        client: httpx.AsyncClient,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        agents_response, teams_response = await asyncio.gather(
            self._get_json(client, "/agents"),
            self._get_json(client, "/teams"),
        )
        agents = [
            self._normalize_entity(item, "agent")
            for item in _as_items(agents_response)
        ]
        teams = [
            self._normalize_entity(item, "team")
            for item in _as_items(teams_response)
        ]
        return agents, teams

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
    ) -> Any | None:
        try:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=self.headers(),
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return None

    def _normalize_entity(self, item: Any, entity_type: str) -> dict[str, Any]:
        data = item if isinstance(item, dict) else {}
        entity_id = (
            data.get("id")
            or data.get(f"{entity_type}_id")
            or data.get("name")
            or "unknown"
        )
        raw_model = data.get("model") if isinstance(data.get("model"), dict) else {}
        model = {
            key: raw_model[key]
            for key in ("id", "name", "model", "provider")
            if isinstance(raw_model.get(key), (str, int, float, bool))
        }
        entity = AgnoEntity(
            id=str(entity_id),
            name=str(data.get("name") or entity_id),
            type=entity_type,
            db_id=str(data.get("db_id") or ""),
            model=model,
        )
        return {
            "id": entity.id,
            "name": entity.name,
            "type": entity.type,
            "db_id": entity.db_id,
            "model": entity.model,
        }

    async def stream_run(
        self,
        *,
        entity_type: str,
        entity_id: str,
        message: str,
        session_id: str = "",
    ) -> AsyncIterator[bytes]:
        if entity_type == "agent":
            path = f"/agents/{entity_id}/runs"
        elif entity_type == "team":
            path = f"/teams/{entity_id}/runs"
        else:
            raise ValueError("Tipo de entidade ainda não suportado.")

        data = {
            "message": message,
            "stream": "true",
            "session_id": session_id,
        }
        headers = self.headers()
        headers.pop("Accept", None)
        try:
            from opentelemetry.propagate import inject

            inject(headers)
        except Exception:
            pass

        timeout = httpx.Timeout(120.0, connect=8.0, read=120.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}{path}",
                headers=headers,
                data=data,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk


def _as_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "agents", "teams"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
