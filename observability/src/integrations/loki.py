from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from observability.src.contracts import ServiceProbe


@dataclass(frozen=True)
class LokiLogsProvider:
    base_url: str
    query: str = '{job="acessilia"}'
    limit: int = 80
    lookback_seconds: int = 3600

    async def probe(self, client: httpx.AsyncClient) -> ServiceProbe:
        try:
            response = await client.get(f"{self.base_url}/ready")
            return ServiceProbe(
                name="loki",
                endpoint=self.base_url,
                available=response.is_success,
                status_code=response.status_code,
            )
        except httpx.HTTPError as exc:
            return ServiceProbe(
                name="loki",
                endpoint=self.base_url,
                available=False,
                error=str(exc),
            )

    async def entries(
        self,
        client: httpx.AsyncClient,
        *,
        search: str = "",
        limit: int | None = None,
    ) -> dict[str, Any]:
        probe = await self.probe(client)
        if not probe.available:
            return {
                "available": False,
                "query_available": False,
                "probe": probe.as_dict(),
                "entries": [],
                "error": probe.error,
            }

        effective_limit = min(max(limit or self.limit, 1), 500)
        effective_query = self.query
        cleaned_search = search.strip()[:500]
        if cleaned_search:
            effective_query = f"{effective_query} |= {json.dumps(cleaned_search)}"

        end_ns = time.time_ns()
        start_ns = end_ns - max(self.lookback_seconds, 60) * 1_000_000_000

        try:
            response = await client.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={
                    "query": effective_query,
                    "limit": str(effective_limit),
                    "direction": "backward",
                    "start": str(start_ns),
                    "end": str(end_ns),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "error":
                raise ValueError(payload.get("error") or "Consulta Loki falhou.")
            streams = payload.get("data", {}).get("result", [])
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "available": True,
                "query_available": False,
                "probe": probe.as_dict(),
                "entries": [],
                "error": str(exc),
            }

        entries: list[dict[str, Any]] = []
        for stream in streams:
            labels = stream.get("stream", {})
            for timestamp_ns, line in stream.get("values", []):
                parsed = parse_loki_line(line)
                entries.append(
                    {
                        "time": loki_timestamp(timestamp_ns),
                        "line": parsed["message"],
                        "level": labels.get("level") or parsed["level"],
                        "module": labels.get("module") or parsed["module"],
                        "format": labels.get("format") or parsed["format"],
                        "service": labels.get("service_name", labels.get("service", "")),
                        "trace_id": labels.get("trace_id") or parsed["trace_id"],
                        "span_id": labels.get("span_id") or parsed["span_id"],
                        "run_id": labels.get("run_id") or parsed["run_id"],
                        "session_id": labels.get("session_id") or parsed["session_id"],
                    }
                )
        entries.sort(key=lambda item: item["time"], reverse=True)
        return {
            "available": True,
            "query_available": True,
            "probe": probe.as_dict(),
            "entries": entries[:effective_limit],
            "query": effective_query,
        }


def parse_loki_line(line: Any) -> dict[str, str]:
    raw_line = line if isinstance(line, str) else str(line)
    parsed = {
        "message": raw_line,
        "level": "",
        "module": "",
        "format": "text",
        "trace_id": "",
        "span_id": "",
        "run_id": "",
        "session_id": "",
    }
    try:
        payload = json.loads(raw_line)
    except (json.JSONDecodeError, TypeError):
        return parsed
    if not isinstance(payload, dict):
        return parsed

    record = payload.get("record")
    if not isinstance(record, dict):
        record = {}
    extra = record.get("extra")
    if not isinstance(extra, dict):
        extra = {}
    level = record.get("level")
    if not isinstance(level, dict):
        level = {}

    parsed.update(
        {
            "message": str(record.get("message") or payload.get("text") or raw_line).strip(),
            "level": str(level.get("name") or ""),
            "module": str(record.get("name") or ""),
            "format": "json",
            "trace_id": str(extra.get("trace_id") or ""),
            "span_id": str(extra.get("span_id") or ""),
            "run_id": str(extra.get("run_id") or ""),
            "session_id": str(extra.get("session_id") or ""),
        }
    )
    return parsed


def loki_timestamp(timestamp_ns: str) -> str:
    try:
        seconds = int(timestamp_ns) / 1_000_000_000
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()
