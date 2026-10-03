#!/usr/bin/env python3
"""Check the remote structural service without loading local OCR models."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from backend.tools.toolbox_client import ToolboxClient


async def check(base_url: str | None, provider: str | None) -> dict:
    client = ToolboxClient(base_url=base_url, provider=provider)
    try:
        return {
            "provider": client.provider,
            "health": await client.health(),
            "capabilities": await client.capabilities(),
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
