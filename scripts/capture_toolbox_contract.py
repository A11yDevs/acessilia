"""Refresh the Toolbox capability/provider contract fixture.

The Toolbox publishes its contract as ``contract/toolbox-contract.json`` in its
repository and on every release (acessilia-toolbox#71); that file is the source
of truth, and CI checks the SDK registry against it (#186).
``tests/fixtures/toolbox-contract.json`` is a copy of it for the offline tests.

``--ref`` copies the published file from a Toolbox branch or tag. ``--url``
captures a running Toolbox instead, which also shows providers registered only
in that deployment; when ``TOOLBOX_API_KEY`` is set it is sent as a Bearer
token. Only the identifiers the checker reads are kept.

Usage:
    python scripts/capture_toolbox_contract.py --ref develop
    python scripts/capture_toolbox_contract.py --url http://localhost:8002
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "toolbox-contract.json"
#: Where the Toolbox publishes its contract, per branch or tag.
PUBLISHED_URL = (
    "https://raw.githubusercontent.com/A11yDevs/acessilia-toolbox/{ref}/contract/toolbox-contract.json"
)

COMMENT = (
    "Toolbox capability/provider contract captured from a running toolbox. "
    "Regenerate with scripts/capture_toolbox_contract.py. Only the fields the "
    "core's contract checker reads are kept, so the fixture stays stable."
)


def _fetch(url: str) -> object:
    request = urllib.request.Request(url)
    api_key = os.getenv("TOOLBOX_API_KEY", "")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"cannot reach the Toolbox at {url}: {exc}")


def build(url: str) -> dict:
    base = url.rstrip("/")
    capabilities = _fetch(f"{base}/v1/capabilities")
    providers = _fetch(f"{base}/v1/providers")

    return {
        "_comment": COMMENT,
        # One entry per published version, as /v1/capabilities lists them: the
        # core checks the exact contract version it was written against.
        "capabilities": [
            {
                "id": entry["id"],
                "version": entry.get("version", 1),
                "providers": sorted(entry.get("providers") or []),
            }
            for entry in sorted(
                capabilities, key=lambda item: (item["id"], item.get("version", 1))
            )
        ],
        "providers": [
            {"id": entry["id"], "capabilities": sorted(entry.get("capabilities") or [])}
            for entry in sorted(providers, key=lambda item: item["id"])
        ],
    }


def published(ref: str) -> dict:
    """The contract the Toolbox publishes at ``ref``, with a comment naming it."""
    data = _fetch(PUBLISHED_URL.format(ref=ref))
    if not isinstance(data, dict) or "capabilities" not in data or "providers" not in data:
        raise SystemExit(f"the Toolbox contract at {ref} is malformed")
    return {
        "_comment": (
            f"Copy of the Toolbox's published contract (contract/toolbox-contract.json "
            f"at {ref}). Refresh with scripts/capture_toolbox_contract.py --ref {ref}; "
            "CI checks the SDK registry against the published file itself."
        ),
        "capabilities": data["capabilities"],
        "providers": data["providers"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ref", help="Toolbox branch or tag whose published contract to copy")
    source.add_argument("--url", help="base URL of a running Toolbox")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    payload = published(args.ref) if args.ref else build(args.url)
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
