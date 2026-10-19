#!/usr/bin/env python3
"""Check the remote structural service without loading local OCR models."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
from acessilia_sdk.toolbox import auth_headers
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from backend.tools.toolbox_client import make_toolbox_client


async def check(base_url: str | None, provider: str | None) -> dict:
    client = make_toolbox_client(
        ToolboxStructureClient,
        **{"base_url": base_url, "provider": provider},
    )
    try:
        endpoint = client.endpoints[0]
        async with httpx.AsyncClient(
            base_url=endpoint.base_url,
            headers=auth_headers(endpoint.api_key or client.api_key),
            timeout=client.timeout_seconds,
        ) as http:
            response = await http.get("/v1/capabilities")
            response.raise_for_status()
            capabilities = response.json()
            if isinstance(capabilities, dict):
                capabilities = capabilities.get("capabilities", capabilities)
        return {
            "provider": client.provider,
            "health": await client.health(),
            "capabilities": capabilities,
        }
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Override TOOLBOX_BASE_URL.")
    parser.add_argument("--provider", help="Override TOOLBOX_PROVIDER.")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(check(args.base_url, args.provider))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
