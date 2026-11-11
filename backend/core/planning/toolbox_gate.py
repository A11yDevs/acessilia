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

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from acessilia_sdk.toolbox import (
    CatalogCache,
    CatalogSnapshot,
    Requirement,
    ToolboxClientConfig,
    ToolboxProviderUnavailable,
    missing_requirements,
    read_first_catalog,
)
from backend.config.settings import settings
from backend.core.manifest.models import ProcessingManifest
from backend.tools.toolbox_client import toolbox_client_config

GATE_MODES = ("observe", "enforce", "off")

#: Reading the catalogue must not hold a document for the extraction timeout.
#: Per request: a refresh makes at most four (one capabilities read, up to three
#: providers reads), so ~40s in the worst case.
CATALOG_TIMEOUT_SECONDS = 10.0

_EXTRACT = "document.structure.extract"

#: Method -> Toolbox requirements, resolved when evaluated so provider overrides
#: in the environment apply. Methods not listed run locally.
METHOD_TOOLBOX_REQUIREMENTS: dict[str, Callable[[], list[Requirement]]] = {
    "dual-provider-fusion": lambda: [
        Requirement(_EXTRACT, settings.toolbox_provider),
        Requirement(_EXTRACT, settings.fusion_secondary_provider),
    ],
    "single-provider": lambda: [Requirement(_EXTRACT, settings.toolbox_provider)],
    # Methods that render pages or regions; pdf.render@2 also renders raster
    # inputs, so they need it for images too.
    "vision-page-inspection": lambda: [
        Requirement("pdf.render", settings.toolbox_pdf_provider)
    ],
    "pymupdf-region": lambda: [
        Requirement("pdf.render", settings.toolbox_pdf_provider)
    ],
    "vlm-pairwise-judge": lambda: [
        Requirement("document.adjudicate.page", settings.toolbox_adjudicate_provider),
        Requirement("pdf.render", settings.toolbox_pdf_provider),
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


def gate_mode() -> str:
    mode = settings.toolbox_availability_gate
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
    catalog_error: str | None = None,
) -> AvailabilityDecision:
    """Which of ``methods`` cannot run against ``snapshot``."""
    blocked: dict[str, list[str]] = {}
    for method in sorted(set(methods)):
        requirements = METHOD_TOOLBOX_REQUIREMENTS.get(method)
        if requirements is None:
            continue
        reasons = missing_requirements(snapshot, requirements())
        if reasons:
            blocked[method] = reasons
    return AvailabilityDecision(
        mode=mode,
        catalog_revision=snapshot.revision if snapshot else None,
        blocked=blocked,
        catalog_error=catalog_error if snapshot is None else None,
    )


def _catalog_config() -> ToolboxClientConfig:
    """The capability clients' configuration: the catalogue is read where they call.

    The endpoints are the clients' (``TOOLBOX_BASE_URLS``, else
    ``TOOLBOX_BASE_URL``), in the same order, with the same key and failover
    log. A URL the SDK cannot use is reported as an unavailable Toolbox, which
    the cache records like any failed read, so a misconfiguration degrades
    planning instead of failing the document.
    """
    try:
        return toolbox_client_config()
    except ValueError as exc:
        raise ToolboxProviderUnavailable(
            f"Toolbox catalogue endpoint is not usable: {exc}"
        ) from exc


async def _fetch() -> CatalogSnapshot:
    """The catalogue of the first endpoint that serves it, on the catalogue's budget.

    Each read has ``CATALOG_TIMEOUT_SECONDS`` per request and no retries (the
    cache's next refresh is the retry). The next endpoint is tried only when
    one is unreachable or times out, as the clients fail over (ADR-0006), and
    the snapshot comes from one deployment. While the primary answers, the
    gate checks the deployment the clients call first.
    """
    config = _catalog_config()
    return await read_first_catalog(
        config.endpoints,
        timeout_seconds=CATALOG_TIMEOUT_SECONDS,
        api_key=config.api_key,
        on_failover=config.on_failover,
    )


_cache: CatalogCache | None = None


def catalog_cache() -> CatalogCache:
    """Process-wide cache, so concurrent documents share one catalogue read."""
    global _cache
    if _cache is None:
        _cache = CatalogCache(
            _fetch,
            refresh_seconds=settings.toolbox_catalog_refresh_seconds,
            stale_seconds=settings.toolbox_catalog_stale_seconds,
        )
    return _cache


async def decide(manifest: ProcessingManifest) -> AvailabilityDecision:
    """Take the catalogue snapshot for one document and evaluate its methods."""
    mode = gate_mode()
    methods = requested_methods(manifest)
    if mode == "off" or not methods & set(METHOD_TOOLBOX_REQUIREMENTS):
        return AvailabilityDecision(mode=mode, catalog_revision=None)
    cache = catalog_cache()
    snapshot = await cache.get()
    return evaluate(methods, snapshot, mode=mode, catalog_error=cache.last_error)


__all__ = [
    "METHOD_TOOLBOX_REQUIREMENTS",
    "AvailabilityDecision",
    "catalog_cache",
    "decide",
    "evaluate",
    "gate_mode",
    "requested_methods",
]
