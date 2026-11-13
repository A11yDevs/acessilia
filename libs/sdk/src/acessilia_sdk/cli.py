"""Command line for the SDK: reach the Toolbox without the core (#402).

    python -m acessilia_sdk --endpoint URL [--endpoint URL ...] \\
        [--api-key-file PATH|-] [--timeout SECONDS] COMMAND ...

    catalog                      the first endpoint's catalogue, as JSON
    run CAPABILITY (--file PATH | --artifact ID) [--provider ...] [--parameters JSON]
                                 call an ``execute`` capability; prints its envelope
    upload FILE                  store a file; prints its artifact id
    download ID OUTPUT           a stored artifact, checked against its digest
    dataset list | describe | splits | items | item | artifact | sample | sync
                                 the dataset routes; JSON, or the artifact's bytes

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
capabilities have routes and arguments of their own, so each has a command
(``REST_COMMANDS``): ``artifact.store`` and ``artifact.retrieve`` are
``upload`` and ``download``, and ``dataset.*`` are the ``dataset``
subcommands, through the SDK's ``ToolboxDatasetClient``. ``run`` points to
them. A capability outside the registry is refused before any request.

Exit status: 0 on success, 1 when the Toolbox or the file system fails
(the typed error is printed on standard error), 2 for invalid arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from acessilia_sdk.toolbox.artifacts import ARTIFACT_ID_RE
from acessilia_sdk.toolbox.capabilities import (
    PROVIDER_DEFAULTS,
    TOOLBOX_CAPABILITIES,
    ToolboxCapability,
)
from acessilia_sdk.toolbox.catalog import CatalogSnapshot, read_catalog
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.clients.artifact import ToolboxArtifactClient
from acessilia_sdk.toolbox.clients.dataset import MAX_PAGE_SIZE, ToolboxDatasetClient
from acessilia_sdk.toolbox.endpoints import ToolboxEndpoint, parse_endpoints
from acessilia_sdk.toolbox.errors import ToolboxError

#: Per-request budget of ``catalog`` without ``--timeout``, as the core's
#: availability gate. The other commands use the clients' own default, since
#: a capability such as an extraction can take minutes.
CATALOG_TIMEOUT_SECONDS = 10.0

#: The command that reaches each ``rest`` capability of the registry.
REST_COMMANDS = {
    "artifact.store": "upload",
    "artifact.retrieve": "download",
    "dataset.list": "dataset list",
    "dataset.describe": "dataset describe",
    "dataset.list_splits": "dataset splits",
    "dataset.list_items": "dataset items",
    "dataset.get_item": "dataset item",
    "dataset.get_artifact": "dataset artifact",
    "dataset.sample": "dataset sample",
    "dataset.sync": "dataset sync",
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
    _dataset_parser(commands)
    return parser


def _count(minimum: int):
    def parse(text: str) -> int:
        value = int(text)
        if value < minimum:
            raise argparse.ArgumentTypeError(f"must be at least {minimum}")
        return value

    return parse


def _dataset_parser(commands) -> None:
    dataset = commands.add_parser(
        "dataset", help="the dataset routes (/v1/datasets) through ToolboxDatasetClient"
    )
    routes = dataset.add_subparsers(dest="route", required=True)

    def route(name: str, help_text: str, *, split: bool = False, revision: bool = True):
        parser = routes.add_parser(name, help=help_text)
        if name != "list":
            parser.add_argument("dataset_id")
        if split:
            parser.add_argument("split")
        if revision:
            parser.add_argument("--revision", help="dataset revision (default: the current one)")
        return parser

    route("list", "every dataset the Toolbox mirrors", revision=False)
    route("describe", "one dataset")
    route("splits", "the splits of a dataset")
    items = route("items", "the items of a split", split=True)
    items.add_argument("--limit", type=_count(0), help="at most this many items")
    items.add_argument("--offset", type=_count(0), default=0, help="skip this many items")
    items.add_argument(
        "--all",
        action="store_true",
        help=f"read every page ({MAX_PAGE_SIZE} items each), up to --limit if given",
    )
    item = route("item", "one item", split=True)
    item.add_argument("item_id")
    artifact = route("artifact", "write one artifact of an item to a file", split=True)
    artifact.add_argument("item_id")
    artifact.add_argument("path", help="the artifact's path in the item")
    artifact.add_argument("output", type=Path, help="file to write; its directory must exist")
    sample = route("sample", "a sample of a split (not retried: one attempt)", split=True)
    sample.add_argument("--n", type=_count(1), default=5, help="sample size (default 5)")
    sync = route("sync", "re-mirror a dataset's artifacts in the Toolbox")
    sync.add_argument("--split", help="only this split")


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
        raise ValueError(
            f"{capability_id} is a REST capability, not an :execute one; "
            f"use the '{REST_COMMANDS[capability_id]}' command"
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


def _write_atomically(output: Path, data: bytes) -> None:
    """Write ``data`` next to ``output`` and move it in place; no partial file."""
    fd, name = tempfile.mkstemp(dir=output.parent, prefix=f".{output.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, output)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


async def _dataset(ctx: _Context, args: argparse.Namespace) -> None:
    client = ctx.client(ToolboxDatasetClient)
    try:
        if args.route == "list":
            result: Any = await client.list_datasets()
        elif args.route == "describe":
            result = await client.describe_dataset(args.dataset_id, args.revision)
        elif args.route == "splits":
            result = await client.list_splits(args.dataset_id, args.revision)
        elif args.route == "items" and args.all:
            result = await client.list_all_items(
                args.dataset_id, args.split, revision=args.revision, limit=args.limit
            )
        elif args.route == "items":
            result = await client.list_items(
                args.dataset_id,
                args.split,
                args.revision,
                limit=100 if args.limit is None else args.limit,
                offset=args.offset,
            )
        elif args.route == "item":
            result = await client.get_item(
                args.dataset_id, args.split, args.item_id, args.revision
            )
        elif args.route == "artifact":
            data = await client.get_dataset_artifact(
                args.dataset_id, args.split, args.item_id, args.path, args.revision
            )
            _write_atomically(args.output, data)
            ctx.stdout.write(f"{args.output}\n")
            return
        elif args.route == "sample":
            result = await client.sample_dataset(
                args.dataset_id, args.split, args.revision, n=args.n
            )
        else:
            result = await client.sync_dataset(
                args.dataset_id,
                args.revision,
                split=args.split,
                timeout_seconds=ctx.timeout,
            )
    finally:
        await client.close()
    json.dump(result, ctx.stdout, indent=2, ensure_ascii=False)
    ctx.stdout.write("\n")


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
            parse_endpoints(args.endpoint),
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
        elif args.command == "dataset":
            if args.route == "items" and args.all and args.offset:
                raise ValueError("--offset does not apply with --all")
            asyncio.run(_dataset(ctx, args))
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


__all__ = [
    "CATALOG_TIMEOUT_SECONDS",
    "REST_COMMANDS",
    "catalog_document",
    "executable_capability",
    "main",
]
