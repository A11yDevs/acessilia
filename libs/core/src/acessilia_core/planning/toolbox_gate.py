"""Availability gate: planning methods checked against the live Toolbox catalogue.

A method whose handler calls the Toolbox declares what it needs (capability and
provider) in ``METHOD_TOOLBOX_REQUIREMENTS``. Before planning a document, the
orchestrator takes one catalogue snapshot and asks :func:`evaluate` which of the
requested methods cannot run against it. The catalogue only restricts: methods
without Toolbox requirements are never affected, and a capability outside the
SDK allowlist is never made available.

``TOOLBOX_AVAILABILITY_GATE`` chooses what happens with the answer:

- ``observe`` (default): report it in the logs and the output metadata, plan as
  before. This is how the gate is validated before it changes plans.
- ``enforce``: remove those methods from the plan. Without a usable catalogue
  every method with Toolbox requirements is removed (fail closed), so the
  planner falls back to local methods or ``human-review``.
- ``off``: no check.
"""

from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from acessilia_sdk.toolbox import (
    CatalogCache,
    CatalogSnapshot,
    Requirement,
    ToolboxEndpoint,
    ToolboxProviderUnavailable,
    missing_requirements,
    read_catalog,
)
from acessilia_core.config import CoreConfig, ToolboxConfig
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.toolbox.toolbox_client import endpoints_from

GATE_MODES = ("observe", "enforce", "off")

#: Reading the catalogue must not hold a document for the extraction timeout.
#: Per request: a refresh makes at most four (one capabilities read, up to three
#: providers reads), so ~40s in the worst case.
CATALOG_TIMEOUT_SECONDS = 10.0

_EXTRACT = "document.structure.extract"

def _provider(config: CoreConfig, key: str) -> str:
    return config.toolbox.providers[key]


#: Method -> Toolbox requirements, resolved from the run's config when
#: evaluated, so the providers checked are the ones the run calls. Methods not
#: listed run locally.
METHOD_TOOLBOX_REQUIREMENTS: dict[str, Callable[[CoreConfig], list[Requirement]]] = {
    "dual-provider-fusion": lambda config: [
        Requirement(_EXTRACT, _provider(config, "toolbox_provider")),
        Requirement(_EXTRACT, config.fusion.secondary_provider),
    ],
    "single-provider": lambda config: [
        Requirement(_EXTRACT, _provider(config, "toolbox_provider"))
    ],
    # Methods that render pages or regions; pdf.render@2 also renders raster
    # inputs, so they need it for images too.
    "vision-page-inspection": lambda config: [
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider"))
    ],
    "pymupdf-region": lambda config: [
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider"))
    ],
    "vlm-pairwise-judge": lambda config: [
        Requirement(
            "document.adjudicate.page", _provider(config, "toolbox_adjudicate_provider")
        ),
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider")),
    ],
}


@dataclass(frozen=True)
class AvailabilityDecision:
    mode: str
    catalog_revision: str | None
    #: Requested methods the catalogue rules out, with the reasons.
    blocked: dict[str, list[str]] = field(default_factory=dict)
    catalog_error: str | None = None

    @property
    def enforced(self) -> bool:
        return self.mode == "enforce"

    @property
    def unavailable_methods(self) -> list[str]:
        """Methods to keep out of the plan (only when enforcing)."""
        return sorted(self.blocked) if self.enforced else []

    def to_metadata(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "catalog_revision": self.catalog_revision,
            "catalog_error": self.catalog_error,
            "blocked_methods": self.blocked,
            "applied": self.enforced and bool(self.blocked),
        }


def gate_mode(toolbox: ToolboxConfig) -> str:
    """``toolbox.availability_gate``, or ``observe`` for a value it does not know."""
    mode = toolbox.availability_gate
    return mode if mode in GATE_MODES else "observe"


def requested_methods(manifest: ProcessingManifest) -> set[str]:
    """Methods the manifest may plan with."""
    return {
        method
        for obligation in manifest.obligations
        for method in obligation.admissible_methods
    }


def evaluate(
    methods: Iterable[str],
    snapshot: CatalogSnapshot | None,
    *,
    mode: str,
    config: CoreConfig,
    catalog_error: str | None = None,
) -> AvailabilityDecision:
    """Which of ``methods`` cannot run against ``snapshot``, with ``config``'s providers."""
    blocked: dict[str, list[str]] = {}
    for method in sorted(set(methods)):
        requirements = METHOD_TOOLBOX_REQUIREMENTS.get(method)
        if requirements is None:
            continue
        reasons = missing_requirements(snapshot, requirements(config))
        if reasons:
            blocked[method] = reasons
    return AvailabilityDecision(
        mode=mode,
        catalog_revision=snapshot.revision if snapshot else None,
        blocked=blocked,
        catalog_error=catalog_error if snapshot is None else None,
    )


def _catalog_endpoint(toolbox: ToolboxConfig) -> ToolboxEndpoint:
    """The capability clients' primary endpoint, so the gate checks where they call.

    The same rule as the clients' (:func:`endpoints_from`). A URL the SDK
    cannot use is reported as an unavailable Toolbox, which the cache records
    like any failed read, so a misconfiguration degrades planning instead of
    failing the document.
    """
    try:
        return endpoints_from(toolbox.base_urls, toolbox.base_url)[0]
    except ValueError as exc:
        raise ToolboxProviderUnavailable(
            f"Toolbox catalogue endpoint is not usable: {exc}"
        ) from exc


async def _fetch(toolbox: ToolboxConfig) -> CatalogSnapshot:
    """The catalogue of the clients' primary endpoint, on the catalogue's budget.

    The primary is the first of ``TOOLBOX_BASE_URLS``, else
    ``TOOLBOX_BASE_URL``: the deployment every capability call goes to first,
    and the one the clients do not check themselves (they check a secondary's
    catalogue before failing over to it). There is deliberately no failover
    here: a secondary's snapshot would admit methods that execution still
    sends to the primary (#429). If the primary's catalogue cannot be read,
    the read fails and ``enforce`` fails closed. Each read has
    ``CATALOG_TIMEOUT_SECONDS`` per request and no retries; the cache's next
    refresh is the retry.
    """
    return await read_catalog(
        _catalog_endpoint(toolbox),
        timeout_seconds=CATALOG_TIMEOUT_SECONDS,
        api_key=toolbox.api_key,
    )


#: How many catalogue sources the process keeps a cache for. The service has
#: one; the bound only stops a process that sees many from keeping them all.
CATALOG_CACHES_MAX = 8

#: The API key's digest in a cache key: a salt per process, and enough rounds
#: for a key derivation (the digest is computed once per document).
_CREDENTIAL_SALT = secrets.token_bytes(16)
_CREDENTIAL_ROUNDS = 10_000

#: One cache per catalogue source and timing, least recently used first.
_caches: OrderedDict[tuple[str, str, int, int], CatalogCache] = OrderedDict()


def _source_key(toolbox: ToolboxConfig) -> tuple[str, str, int, int]:
    """What decides the snapshot: the primary endpoint, the key, the timings.

    The endpoint is the normalized primary, the only one the catalogue is
    read from, so equivalent spellings share a cache; an unusable URL keys on
    its text, and its cache records the error. The API key enters as a
    salted PBKDF2 digest with a salt drawn per process, so the key of the
    table holds no credential and its digest means nothing outside the
    process (the cache's reader still needs the key, and goes with the
    entry).
    """
    try:
        endpoint = endpoints_from(toolbox.base_urls, toolbox.base_url)[0].base_url
    except ValueError:
        endpoint = f"unusable:{toolbox.base_urls}|{toolbox.base_url}"
    credential = hashlib.pbkdf2_hmac(
        "sha256", toolbox.api_key.encode("utf-8"), _CREDENTIAL_SALT, _CREDENTIAL_ROUNDS
    ).hex()
    return (
        endpoint,
        credential,
        toolbox.catalog_refresh_seconds,
        toolbox.catalog_stale_seconds,
    )


def catalog_cache(toolbox: ToolboxConfig) -> CatalogCache:
    """The process-wide cache for ``toolbox``'s catalogue.

    Concurrent documents with the same primary endpoint, key and timings
    share one catalogue read. A run with another of these gets its own
    cache, so it never reads a snapshot taken from a deployment it does not
    call, or with a key it does not hold. At most ``CATALOG_CACHES_MAX``
    caches are kept; the least recently used one goes first.
    """
    key = _source_key(toolbox)
    cache = _caches.get(key)
    if cache is None:
        cache = _caches[key] = CatalogCache(
            lambda: _fetch(toolbox),
            refresh_seconds=toolbox.catalog_refresh_seconds,
            stale_seconds=toolbox.catalog_stale_seconds,
        )
        while len(_caches) > CATALOG_CACHES_MAX:
            _caches.popitem(last=False)
    else:
        _caches.move_to_end(key)
    return cache


async def decide(manifest: ProcessingManifest, config: CoreConfig) -> AvailabilityDecision:
    """Take the catalogue snapshot for one document and evaluate its methods."""
    mode = gate_mode(config.toolbox)
    methods = requested_methods(manifest)
    if mode == "off" or not methods & set(METHOD_TOOLBOX_REQUIREMENTS):
        return AvailabilityDecision(mode=mode, catalog_revision=None)
    cache = catalog_cache(config.toolbox)
    snapshot = await cache.get()
    return evaluate(
        methods, snapshot, mode=mode, config=config, catalog_error=cache.last_error
    )


__all__ = [
    "METHOD_TOOLBOX_REQUIREMENTS",
    "AvailabilityDecision",
    "catalog_cache",
    "decide",
    "evaluate",
    "gate_mode",
    "requested_methods",
]
