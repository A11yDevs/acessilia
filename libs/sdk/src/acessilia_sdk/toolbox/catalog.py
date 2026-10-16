"""The Toolbox catalogue as seen by a client, and the checks made against it.

A client decides which operations it may plan with from two sources: the local
allowlist (``TOOLBOX_CAPABILITIES``, with the exact contract versions it was
written against) and the catalogue the Toolbox currently publishes. The
catalogue only ever **restricts** that set: a capability the Toolbox advertises
but the allowlist does not name is never made available.

``CatalogCache`` keeps the last good snapshot so a brief Toolbox outage does not
take every remote operation away at once; past its staleness limit it returns
``None`` and the caller is expected to fail closed.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from acessilia_sdk.toolbox.capabilities import TOOLBOX_CAPABILITIES
from acessilia_sdk.toolbox.errors import (
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)
from acessilia_sdk.toolbox.transport import raise_for_error


@dataclass(frozen=True)
class CatalogSnapshot:
    """What one Toolbox deployment publishes, reduced to what clients check."""

    #: Content hash of ``capabilities`` and ``bindings``; equal revisions mean
    #: the same catalogue, whichever replica answered.
    revision: str
    #: Capability id -> manifest version.
    capabilities: Mapping[str, int]
    #: Registered provider id -> capability ids it implements. Read from
    #: ``/v1/providers``, which lists registered providers, rather than from the
    #: provider names a capability manifest declares.
    bindings: Mapping[str, frozenset[str]]
    #: ``time.monotonic()`` when the snapshot was taken.
    fetched_at: float = field(compare=False)


@dataclass(frozen=True)
class Requirement:
    """A capability an operation calls, with the provider it calls it on."""

    capability_id: str
    provider: str


def snapshot_from_payloads(
    capabilities: Any, providers: Any, *, fetched_at: float
) -> CatalogSnapshot:
    """Build a snapshot from ``/v1/capabilities`` and ``/v1/providers`` bodies."""
    if not isinstance(capabilities, list) or not isinstance(providers, list):
        raise ToolboxContractViolation(
            "Catálogo da Toolbox deve ser uma lista de capacidades e de providers"
        )
    versions: dict[str, int] = {}
    for entry in capabilities:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ToolboxContractViolation("Capacidade sem id no catálogo da Toolbox")
        capability_id = str(entry["id"])
        version = int(entry.get("version") or 1)
        versions[capability_id] = max(version, versions.get(capability_id, 0))
    bindings: dict[str, frozenset[str]] = {}
    for entry in providers:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ToolboxContractViolation("Provider sem id no catálogo da Toolbox")
        bindings[str(entry["id"])] = frozenset(
            str(item) for item in entry.get("capabilities") or []
        )
    canonical = json.dumps(
        {
            "capabilities": sorted(versions.items()),
            "bindings": sorted((k, sorted(v)) for k, v in bindings.items()),
        },
        separators=(",", ":"),
    )
    return CatalogSnapshot(
        revision=hashlib.sha256(canonical.encode()).hexdigest()[:16],
        capabilities=versions,
        bindings=bindings,
        fetched_at=fetched_at,
    )


async def fetch_catalog(
    http: httpx.AsyncClient, *, clock: Callable[[], float] = time.monotonic
) -> CatalogSnapshot:
    """Read the catalogue a Toolbox publishes.

    The two routes are separate requests, so a redeploy (or another replica)
    between them could produce a pair from two catalogues. The pair is read
    until two consecutive reads agree on the revision, at most three times.
    """

    async def read() -> CatalogSnapshot:
        return snapshot_from_payloads(
            await _get_json(http, "/v1/capabilities"),
            await _get_json(http, "/v1/providers"),
            fetched_at=clock(),
        )

    previous = await read()
    for _ in range(2):
        current = await read()
        if current.revision == previous.revision:
            return current
        previous = current
    raise ToolboxContractViolation(
        "Catálogo da Toolbox mudou durante a leitura; tente novamente"
    )


def missing_requirements(
    snapshot: CatalogSnapshot | None, requirements: Iterable[Requirement]
) -> list[str]:
    """Why ``requirements`` cannot be met; an empty list means they all can.

    Without a snapshot nothing remote can be confirmed, so every requirement is
    reported (fail closed).
    """
    reasons: list[str] = []
    for requirement in requirements:
        capability_id, provider = requirement.capability_id, requirement.provider
        spec = TOOLBOX_CAPABILITIES.get(capability_id)
        if spec is None:
            reasons.append(f"{capability_id}: fora da allowlist do SDK")
            continue
        if snapshot is None:
            reasons.append(f"{capability_id}: catálogo da Toolbox indisponível")
            continue
        published = snapshot.capabilities.get(capability_id)
        if published is None:
            reasons.append(f"{capability_id}: não publicada pela Toolbox")
            continue
        if published != spec.contract_version:
            reasons.append(
                f"{capability_id}: Toolbox publica v{published}, "
                f"cliente espera v{spec.contract_version}"
            )
            continue
        implemented = snapshot.bindings.get(provider)
        if implemented is None:
            reasons.append(f"{capability_id}: provider {provider} não registrado")
        elif capability_id not in implemented:
            reasons.append(
                f"{capability_id}: provider {provider} não implementa a capacidade"
            )
    return reasons


class CatalogCache:
    """Last good catalogue, refreshed at most every ``refresh_seconds``.

    When a refresh fails the previous snapshot keeps being served until it is
    ``stale_seconds`` old; after that :meth:`get` returns ``None``.
    """

    def __init__(
        self,
        fetch: Callable[[], Awaitable[CatalogSnapshot]],
        *,
        refresh_seconds: float = 60.0,
        stale_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self.refresh_seconds = refresh_seconds
        self.stale_seconds = max(stale_seconds, refresh_seconds)
        self._clock = clock
        self._snapshot: CatalogSnapshot | None = None
        self.last_error: str | None = None

    async def get(self) -> CatalogSnapshot | None:
        now = self._clock()
        cached = self._snapshot
        if cached is not None and now - cached.fetched_at < self.refresh_seconds:
            return cached
        try:
            self._snapshot = await self._fetch()
            self.last_error = None
            return self._snapshot
        except ToolboxError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        if cached is not None and now - cached.fetched_at < self.stale_seconds:
            return cached
        return None


async def _get_json(http: httpx.AsyncClient, path: str) -> Any:
    try:
        response = await http.get(path)
    except httpx.TimeoutException as e:
        raise ToolboxTimeout(f"Timeout em GET {path}: {e}") from e
    except httpx.RequestError as e:
        raise ToolboxProviderUnavailable(
            f"Toolbox indisponível em {http.base_url}: {e}"
        ) from e
    raise_for_error(response, path)
    try:
        return response.json()
    except ValueError as e:
        raise ToolboxContractViolation(f"Resposta de {path} não contém JSON válido") from e


__all__ = [
    "CatalogCache",
    "CatalogSnapshot",
    "Requirement",
    "fetch_catalog",
    "missing_requirements",
    "snapshot_from_payloads",
]
