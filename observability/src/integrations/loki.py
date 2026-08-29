from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class LokiLogsProvider:
    base_url: str
    query: str = '{job="acessilia"}'
    limit: int = 80

    async def entries(self, client: httpx.AsyncClient) -> dict[str, Any]:
        try:
            response = await client.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={
                    "query": self.query,
                    "limit": str(self.limit),
                    "direction": "backward",
                },
            )
            response.raise_for_status()
            streams = response.json().get("data", {}).get("result", [])
        except Exception:
            return {"available": False, "entries": []}

        entries: list[dict[str, Any]] = []
        for stream in streams:
            labels = stream.get("stream", {})
            for timestamp_ns, line in stream.get("values", []):
                entries.append(
                    {
                        "time": loki_timestamp(timestamp_ns),
                        "line": line,
                        "level": labels.get("level", ""),
                        "module": labels.get("module", ""),
                        "format": labels.get("format", ""),
                    }
                )
        entries.sort(key=lambda item: item["time"], reverse=True)
        return {"available": True, "entries": entries[: self.limit]}


def loki_timestamp(timestamp_ns: str) -> str:
    try:
        seconds = int(timestamp_ns) / 1_000_000_000
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()
