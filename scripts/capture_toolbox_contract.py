"""Capture the Toolbox capability/provider contract into a fixture.

Regenerates ``tests/fixtures/toolbox-contract.json`` from a running Toolbox so
the offline contract check in CI keeps tracking the catalogue the core is
expected to talk to. Only the identifiers the checker reads are kept; the
Toolbox already masks provider credentials in ``/v1/providers``.

Usage:
    python scripts/capture_toolbox_contract.py --url http://localhost:8002
    python scripts/capture_toolbox_contract.py --url https://host/toolbox --out tests/fixtures/toolbox-contract.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "toolbox-contract.json"

COMMENT = (
    "Toolbox capability/provider contract captured from a running toolbox. "
    "Regenerate with scripts/capture_toolbox_contract.py. Only the fields the "
    "core's contract checker reads are kept, so the fixture stays stable."
)


def _fetch(url: str) -> object:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"cannot reach the Toolbox at {url}: {exc}")


def build(url: str) -> dict:
    base = url.rstrip("/")
    capabilities = _fetch(f"{base}/v1/capabilities")
    providers = _fetch(f"{base}/v1/providers")

    return {
        "_comment": COMMENT,
        "capabilities": [
            {"id": entry["id"], "providers": sorted(entry.get("providers") or [])}
            for entry in sorted(capabilities, key=lambda item: item["id"])
        ],
        "providers": [
            {"id": entry["id"], "capabilities": sorted(entry.get("capabilities") or [])}
            for entry in sorted(providers, key=lambda item: item["id"])
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="base URL of a running Toolbox")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    payload = build(args.url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {args.out} "
        f"({len(payload['capabilities'])} capabilities, "
        f"{len(payload['providers'])} providers)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
