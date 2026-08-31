from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from observability.src.integrations.http import json_or_none


@dataclass(frozen=True)
class ProjectApiClient:
    base_url: str
    health_path: str = "/api/v1/health"
    stats_path: str = "/api/v1/stats"
    history_path: str = "/api/v1/history?limit=20"

    async def snapshot(self, client: httpx.AsyncClient) -> dict[str, Any]:
        health, stats, history = await asyncio.gather(
            json_or_none(client, self.base_url, self.health_path),
            json_or_none(client, self.base_url, self.stats_path),
            json_or_none(client, self.base_url, self.history_path),
        )
        return {
            "health": health,
            "stats": stats,
            "history": history or [],
        }
