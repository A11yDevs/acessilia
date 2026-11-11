"""Command line for the SDK: reach the Toolbox without the core (#402).

    python -m acessilia_sdk --endpoint URL [--endpoint URL ...] \\
        [--api-key-file PATH|-] [--timeout SECONDS] COMMAND ...

    catalog                      the first endpoint's catalogue, as JSON
    run CAPABILITY (--file PATH | --artifact ID) [--provider ...] [--parameters JSON]
                                 call an ``execute`` capability; prints its envelope
    upload FILE                  store a file; prints its artifact id
    download ID OUTPUT           a stored artifact, checked against its digest

Every value comes from the arguments: the SDK reads no settings and no
environment (ADR-0002). The API key is read from a file (``-`` for standard
input) so it never appears in the process list. ``catalog`` reads the first
endpoint, the one every capability call goes to first. The other commands try
the endpoints in order, like the capability clients (ADR-0006, ADR-0014), and
report each endpoint they leave on standard error, so a failover is never
silent even when the call succeeds.

``run`` dispatches by transport. Capabilities in the SDK's registry with the
``execute`` transport go through ``POST /v1/capabilities/{id}:execute``, with
the registry's provider unless ``--provider`` says otherwise. ``rest``
capabilities have routes and arguments of their own: ``artifact.store`` and
``artifact.retrieve`` are the ``upload`` and ``download`` commands, and the
``dataset.*`` routes are the SDK's ``ToolboxDatasetClient``. A capability
outside the registry is refused before any request.

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
from typing import Any, TextIO
from urllib.parse import urlsplit

import httpx

from acessilia_sdk.toolbox.artifacts import ARTIFACT_ID_RE
from acessilia_sdk.toolbox.capabilities import (
    PROVIDER_DEFAULTS,
    TOOLBOX_CAPABILITIES,
    ToolboxCapability,
)
from acessilia_sdk.toolbox.catalog import CatalogSnapshot, read_catalog
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.clients.artifact import ToolboxArtifactClient
from acessilia_sdk.toolbox.endpoints import ToolboxEndpoint, parse_endpoints
from acessilia_sdk.toolbox.errors import ToolboxError

#: Per-request budget of ``catalog`` without ``--timeout``, as the core's
#: availability gate. The other commands use the clients' own default, since
#: a capability such as an extraction can take minutes.
CATALOG_TIMEOUT_SECONDS = 10.0

#: The ``rest`` capabilities a command covers, and where the others are.
REST_COMMANDS = {
    "artifact.store": "the 'upload' command",
    "artifact.retrieve": "the 'download' command",
}

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m acessilia_sdk",
        description="Reach the Acessilia Toolbox through its published HTTP contract.",
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
        metavar="SECONDS",
        help=(
            f"per-request timeout (catalog: {CATALOG_TIMEOUT_SECONDS:g} s; "
            "other commands: the SDK clients' default)"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="print the first endpoint's catalogue as JSON")

    run = commands.add_parser(
        "run", help="call an execute capability of the SDK's registry; prints its envelope"
    )
    run.add_argument("capability", help="capability id, e.g. media.inspect")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, metavar="PATH", help="input file to upload")
    source.add_argument(
        "--artifact", metavar="ID", help="input already stored in the Toolbox (see 'upload')"
    )
    run.add_argument("--provider", help="provider id (default: the registry's)")
    run.add_argument("--language", help="input language, e.g. pt-BR")
    run.add_argument(
        "--parameters", metavar="JSON", help="capability parameters, as a JSON object"
    )
    run.add_argument(
        "--no-cache", action="store_true", help="do not reuse a cached Toolbox result"
    )

    upload = commands.add_parser("upload", help="store a file; prints its artifact id")
    upload.add_argument("file", type=Path)

    download = commands.add_parser(
        "download", help="download a stored artifact, checked against its digest"
    )
    download.add_argument("artifact_id", help="sha256:<64 hex> or <64 hex>")
    download.add_argument("output", type=Path, help="file to write; its directory must exist")
    return parser


def _endpoints(urls: Sequence[str]) -> tuple[ToolboxEndpoint, ...]:
    """The endpoints, each also accepted by the HTTP client, or ``ValueError``.

    ``ToolboxEndpoint`` checks the scheme and the host. A port that is not a
    number makes httpx fail only when a client is built, and one out of range
    (``:99999``) only when it connects. Checking both here keeps every unusable
    URL an invalid argument, reported before any request.
    """
    endpoints = parse_endpoints(urls)
    for endpoint in endpoints:
        try:
            httpx.URL(endpoint.base_url)
            urlsplit(endpoint.base_url).port
        except (httpx.InvalidURL, ValueError) as exc:
            raise ValueError(f"unusable endpoint {endpoint.base_url!r}: {exc}") from exc
    return endpoints


def _read_api_key(path: str | None, stdin: TextIO) -> str:
    if path is None:
        return ""
    text = stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return text.strip()


def _artifact_id(value: str) -> str:
    if not ARTIFACT_ID_RE.fullmatch(value):
        raise ValueError(f"not an artifact id: {value!r}")
    return value


def _input_file(path: Path) -> Path:
    if not path.is_file():
        raise ValueError(f"not a file: {str(path)!r}")
    return path


def executable_capability(capability_id: str) -> ToolboxCapability:
    """The registry entry ``run`` can call, or ``ValueError`` saying why not."""
    spec = TOOLBOX_CAPABILITIES.get(capability_id)
    if spec is None:
        raise ValueError(
            f"{capability_id!r} is not in the SDK's capability registry; "
            "the SDK calls only the contracts it was written against"
        )
    if spec.transport != "execute":
        where = REST_COMMANDS.get(capability_id, "the SDK's ToolboxDatasetClient")
        raise ValueError(
            f"{capability_id} is a REST capability, not an :execute one; use {where}"
        )
    return spec


def _parameters(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--parameters is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("--parameters must be a JSON object")
    return value


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


class _Context:
    """What every command needs: endpoints, key, timeout and the output streams."""

    def __init__(
        self,
        endpoints: tuple[ToolboxEndpoint, ...],
        api_key: str,
        timeout: float | None,
        stdout: TextIO,
        stderr: TextIO,
    ) -> None:
        self.endpoints = endpoints
        self.api_key = api_key
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr

    def report_failover(self, endpoint: ToolboxEndpoint, error: ToolboxError) -> None:
        # Called for each endpoint that failed, the last one included, so it
        # does not promise another attempt: the final error, if any, follows.
        self.stderr.write(
            f"warning: endpoint {endpoint.base_url} failed: {type(error).__name__}: {error}\n"
        )

    def client(self, cls: type[ToolboxCapabilityClient], **kwargs: Any):
        return cls(
            endpoints=self.endpoints,
            api_key=self.api_key,
            timeout_seconds=self.timeout,
            on_failover=self.report_failover,
            **kwargs,
        )


async def _catalog(ctx: _Context) -> None:
    snapshot = await read_catalog(
        ctx.endpoints[0],
        timeout_seconds=ctx.timeout or CATALOG_TIMEOUT_SECONDS,
        api_key=ctx.api_key,
    )
    json.dump(catalog_document(ctx.endpoints[0], snapshot), ctx.stdout, indent=2)
    ctx.stdout.write("\n")


async def _run(
    ctx: _Context,
    spec: ToolboxCapability,
    *,
    provider: str | None,
    file_path: Path | None,
    artifact_id: str | None,
    language: str | None,
    parameters: dict[str, Any] | None,
    no_cache: bool,
) -> None:
    provider = provider or (
        PROVIDER_DEFAULTS.get(spec.provider_key) if spec.provider_key else None
    )
    if not provider:
        raise ValueError(f"{spec.id} has no default provider; pass --provider")
    client = ctx.client(ToolboxCapabilityClient, provider=provider)
    try:
        # The base client's call: the registry check, failover, retries for
        # idempotent capabilities and the typed errors of every client.
        envelope = await client._execute(
            spec.id,
            provider=provider,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            parameters=parameters,
            no_cache=no_cache,
        )
    finally:
        await client.close()
    json.dump(envelope, ctx.stdout, indent=2, ensure_ascii=False)
    ctx.stdout.write("\n")


async def _upload(ctx: _Context, file_path: Path) -> None:
    client = ctx.client(ToolboxArtifactClient)
    try:
        artifact_id = await client.upload(file_path)
    finally:
        await client.close()
    ctx.stdout.write(f"{artifact_id}\n")


async def _download(ctx: _Context, artifact_id: str, output: Path) -> None:
    client = ctx.client(ToolboxArtifactClient)
    try:
        await client.download(artifact_id, output)
    finally:
        await client.close()
    ctx.stdout.write(f"{output}\n")


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
        # Every argument is checked before the first request.
        if args.timeout is not None and args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        ctx = _Context(
            _endpoints(args.endpoint),
            _read_api_key(args.api_key_file, stdin),
            args.timeout,
            stdout,
            stderr,
        )
        if args.command == "catalog":
            asyncio.run(_catalog(ctx))
        elif args.command == "run":
            spec = executable_capability(args.capability)
            asyncio.run(
                _run(
                    ctx,
                    spec,
                    provider=args.provider,
                    file_path=_input_file(args.file) if args.file else None,
                    artifact_id=_artifact_id(args.artifact) if args.artifact else None,
                    language=args.language,
                    parameters=_parameters(args.parameters),
                    no_cache=args.no_cache,
                )
            )
        elif args.command == "upload":
            asyncio.run(_upload(ctx, _input_file(args.file)))
        else:
            asyncio.run(_download(ctx, _artifact_id(args.artifact_id), args.output))
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


__all__ = ["CATALOG_TIMEOUT_SECONDS", "catalog_document", "executable_capability", "main"]
