from __future__ import annotations

from typing import Any

import httpx

from observability.src.contracts import ServiceProbe


async def json_or_none(
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
) -> Any | None:
    try:
        response = await client.get(f"{base_url}{path}")
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


async def service_probe(
    client: httpx.AsyncClient,
    *,
    name: str,
    base_url: str,
    path: str = "/",
) -> ServiceProbe:
    try:
        response = await client.get(f"{base_url}{path}")
        return ServiceProbe(
            name=name,
            endpoint=base_url,
            available=response.status_code < 500,
            status_code=response.status_code,
        )
    except Exception as exc:
        return ServiceProbe(
            name=name,
            endpoint=base_url,
            available=False,
            error=str(exc),
        )


async def is_http_available(
    client: httpx.AsyncClient,
    base_url: str,
    path: str = "/",
) -> bool:
    return (await service_probe(client, name="http", base_url=base_url, path=path)).available
