"""Command line for the SDK: read the Toolbox without the core (#402).

    python -m acessilia_sdk --endpoint URL [--endpoint URL ...] \\
        [--api-key-file PATH|-] [--timeout SECONDS] COMMAND ...

    catalog              the first endpoint's catalogue, as JSON
    download ID OUTPUT   a stored artifact, checked against its digest

Every value comes from the arguments: the SDK reads no settings and no
environment (ADR-0002). The API key is read from a file (``-`` for standard
input) so it never appears in the process list. ``catalog`` reads the first
endpoint, the one every capability call goes to first; ``download`` tries the
endpoints in order, like the capability clients (ADR-0006, ADR-0014).

Exit status: 0 on success, 1 when the Toolbox or the file system fails
(the typed error is printed on standard error), 2 for invalid arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from acessilia_sdk.toolbox.artifacts import ARTIFACT_ID_RE
from acessilia_sdk.toolbox.catalog import CatalogSnapshot, read_catalog
from acessilia_sdk.toolbox.clients.artifact import ToolboxArtifactClient
from acessilia_sdk.toolbox.endpoints import ToolboxEndpoint, parse_endpoints
from acessilia_sdk.toolbox.errors import ToolboxError

#: Per-request budget of the catalogue read, as the core's availability gate.
DEFAULT_TIMEOUT_SECONDS = 10.0

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m acessilia_sdk",
        description="Read the Acessilia Toolbox through its published HTTP contract.",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        required=True,
        metavar="URL",
        help="Toolbox base URL; repeat for independent deployments, tried in order",
    )
    parser.add_argument(
        "--api-key-file",
        metavar="PATH",
        help="file holding the API key ('-' reads standard input); none sends no key",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=f"per-request timeout (default {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="print the first endpoint's catalogue as JSON")
    download = commands.add_parser(
        "download", help="download a stored artifact, checked against its digest"
    )
    download.add_argument("artifact_id", help="sha256:<64 hex> or <64 hex>")
    download.add_argument("output", type=Path, help="file to write; its directory must exist")
    return parser


def _read_api_key(path: str | None, stdin: TextIO) -> str:
    if path is None:
        return ""
    text = stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return text.strip()


def catalog_document(endpoint: ToolboxEndpoint, snapshot: CatalogSnapshot) -> dict:
    """The JSON the ``catalog`` command prints."""
    return {
        "endpoint": endpoint.base_url,
        "revision": snapshot.revision,
        "capabilities": dict(sorted(snapshot.capabilities.items())),
        "providers": {
            provider: sorted(capabilities)
            for provider, capabilities in sorted(snapshot.bindings.items())
        },
    }


async def _catalog(
    endpoints: tuple[ToolboxEndpoint, ...], api_key: str, timeout: float, stdout: TextIO
) -> None:
    snapshot = await read_catalog(endpoints[0], timeout_seconds=timeout, api_key=api_key)
    json.dump(catalog_document(endpoints[0], snapshot), stdout, indent=2)
    stdout.write("\n")


async def _download(
    endpoints: tuple[ToolboxEndpoint, ...],
    api_key: str,
    timeout: float,
    artifact_id: str,
    output: Path,
    stdout: TextIO,
) -> None:
    client = ToolboxArtifactClient(
        endpoints=endpoints, api_key=api_key, timeout_seconds=timeout
    )
    try:
        await client.download(artifact_id, output)
    finally:
        await client.close()
    stdout.write(f"{output}\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the command line; returns the exit status."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = _parser().parse_args(argv)
    try:
        if args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        endpoints = parse_endpoints(args.endpoint)
        api_key = _read_api_key(args.api_key_file, stdin)
        if args.command == "download" and not ARTIFACT_ID_RE.match(args.artifact_id):
            raise ValueError(f"not an artifact id: {args.artifact_id!r}")
        if args.command == "catalog":
            asyncio.run(_catalog(endpoints, api_key, args.timeout, stdout))
        else:
            asyncio.run(
                _download(
                    endpoints, api_key, args.timeout, args.artifact_id, args.output, stdout
                )
            )
    except ToolboxError as exc:
        stderr.write(f"error: {type(exc).__name__}: {exc}\n")
        return EXIT_FAILED
    except ValueError as exc:
        stderr.write(f"error: {exc}\n")
        return EXIT_USAGE
    except OSError as exc:
        stderr.write(f"error: {type(exc).__name__}: {exc}\n")
        return EXIT_FAILED
    return EXIT_OK


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "catalog_document", "main"]
