"""Availability gate: planning methods checked against the live Toolbox catalogue.

A method whose handler calls the Toolbox declares what it needs (capability and
provider) in ``METHOD_TOOLBOX_REQUIREMENTS``. Before planning a document, the
orchestrator takes one catalogue snapshot and asks :func:`evaluate` which of the
requested methods cannot run against it. The catalogue only restricts: methods
without Toolbox requirements are never affected, and a capability outside the
SDK allowlist is never made available.

``TOOLBOX_AVAILABILITY_GATE`` chooses whether the snapshot is read at all:

- ``enforce`` (default): the snapshot is the input. Its facts reach the planner
  (:meth:`AvailabilityDecision.catalogue_facts`): each method's requirements
  and what the snapshot offers, from which the domain derives ``runnable``.
  Without a usable catalogue every method with Toolbox requirements is ruled
  out (fail closed), so the planner falls back to local methods or
  ``human-review``. The gate itself only reports the decision in the logs and
  the output metadata.
- ``off``: no check; an emergency switch. Every method runs as if the
  catalogue offered everything.

The former ``observe`` mode (report and plan as before) was removed once the
snapshot became the problem's input (#809). An unknown value, including a
deployment still configured with ``observe``, uses ``enforce``.

Since domain 2.4 (#640) the decision reaches the planner as problem facts.

A method's Toolbox calls are of three kinds (#848):

- **required** (``METHOD_TOOLBOX_REQUIREMENTS``): missing one rules the
  method out;
- **optional** (``METHOD_OPTIONAL_CAPABILITIES``): missing one degrades the
  method per element (a picture left with ``crop_unavailable``, a formula
  read by the vision fallback, a table without its inline math), so it
  never rules the method out. The decision records the missing ones as
  ``degraded_methods``, which reach the output metadata. It is per method,
  not per document: a method whose document never makes the call (a DOCX
  picture carries its bytes; a DOCX formula is not rendered) is still
  reported, so it *may* run degraded (#859);
- none: the method runs in the core alone.

Where a method's implementation lives (``LOCAL_METHODS``' role, such as
``transitional``) is a separate dimension: a transitional method can still
have optional capabilities.
"""

from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from acessilia_core.config import CoreConfig, ToolboxConfig
from acessilia_core.logger import logger
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.planning.pddl_processor import CatalogueFacts
from acessilia_core.toolbox.toolbox_client import endpoints_from
from acessilia_sdk.toolbox import (
    TOOLBOX_CAPABILITIES,
    CatalogCache,
    CatalogSnapshot,
    Requirement,
    ToolboxEndpoint,
    ToolboxProviderUnavailable,
    missing_requirements,
    read_catalog,
)

GATE_MODES = ("enforce", "off")

#: Reading the catalogue must not hold a document for the extraction timeout.
#: Per request: a refresh makes at most four (one capabilities read, up to three
#: providers reads), so ~40s in the worst case.
CATALOG_TIMEOUT_SECONDS = 10.0

_EXTRACT = "document.structure.extract"

def _provider(config: CoreConfig, key: str) -> str:
    """The provider the client calls: the setting, or the registry default
    when it is empty, as ``ToolboxCapabilityClient`` resolves it. Required
    and optional calls resolve it the same way (#856 review): an empty
    ``TOOLBOX_PDF_PROVIDER`` used to block, under ``enforce``, a method the
    client runs with the default provider."""
    from acessilia_sdk.toolbox.capabilities import provider_default

    return config.toolbox.providers[key] or provider_default(key)


#: Method -> Toolbox requirements, resolved from the run's config when
#: evaluated, so the providers checked are the ones the run calls. Every
#: method whose handler needs the Toolbox to run is listed (#789); one whose
#: calls only degrade it is in ``METHOD_OPTIONAL_CAPABILITIES`` (#848), and
#: every method without requirements is in ``LOCAL_METHODS`` or
#: ``NEVER_AVAILABLE_METHODS`` below.
METHOD_TOOLBOX_REQUIREMENTS: dict[str, Callable[[CoreConfig], list[Requirement]]] = {
    "norm-fix": lambda config: [
        Requirement("document.text.normalize", _provider(config, "toolbox_text_normalize_provider"))
    ],
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
    # The formula handler converts and verbalizes LaTeX through the Toolbox
    # (#789); both use the math transform provider.
    "mathml": lambda config: [
        Requirement("math.convert", _provider(config, "toolbox_math_provider"))
    ],
    "latex-verbalizer": lambda config: [
        Requirement("math.verbalize", _provider(config, "toolbox_math_provider"))
    ],
    "vlm-pairwise-judge": lambda config: [
        Requirement(
            "document.adjudicate.page", _provider(config, "toolbox_adjudicate_provider")
        ),
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider")),
    ],
}


#: Method -> the Toolbox calls whose absence only degrades it (#848): the
#: method still runs, and the elements it could not serve keep their reason.
#: Resolved from the run's config, like the requirements. A method is in this
#: map or in ``METHOD_TOOLBOX_REQUIREMENTS``, never both.
METHOD_OPTIONAL_CAPABILITIES: dict[str, Callable[[CoreConfig], list[Requirement]]] = {
    # A picture's crop; without it the picture records crop_unavailable.
    "picture-description": lambda config: [
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider"))
    ],
    # The text layer's spans; without them the detection records
    # `unavailable` and the prose keeps its text.
    "inline-math-marker": lambda config: [
        Requirement("document.text.spans", _provider(config, "toolbox_pdf_provider"))
    ],
    # A formula region's crop; without it the region stays unclassified
    # (crop_unavailable) and takes the formula path.
    "formula-region-classifier": lambda config: [
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider"))
    ],
    # math.recognize degrades to the vision fallback; without pdf.render a
    # formula has no crop and records crop_unavailable.
    "formula-recognizer": lambda config: [
        Requirement("math.recognize", _provider(config, "toolbox_math_recognize_provider")),
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider")),
    ],
    # pdf.render only for a table read again; document.text.spans for the
    # cells' inline math, recorded as unavailable without it.
    "table-enrichment": lambda config: [
        Requirement("pdf.render", _provider(config, "toolbox_pdf_provider")),
        Requirement("document.text.spans", _provider(config, "toolbox_pdf_provider")),
    ],
}


#: Roles of the methods without Toolbox requirements (#789); a method here
#: may still have optional capabilities (#848):
#: - ``transitional``: document computation still running in the core. Not a
#:   permanent allowance: ADR-0028 moves it to Toolbox capabilities (#804), and
#:   the method then moves to ``METHOD_TOOLBOX_REQUIREMENTS``;
#: - ``validation``: checks work done before planning; that work becomes a
#:   planned action (ADR-0029, #640 PR 2);
#: - ``symbolic``: a workflow decision that stays in the core.
LOCAL_ROLES = ("transitional", "validation", "symbolic")

#: Method -> (role, reason) for every method without required Toolbox calls
#: (it may have optional ones), so the catalogue cannot rule it out. An inventory of the current state, kept
#: complete by ``tests/test_toolbox_availability_gate.py``.
LOCAL_METHODS: dict[str, tuple[str, str]] = {
    "deterministic-heading-repair": ("transitional", "docstruct heading repair"),
    "latex-normalizer": ("transitional", "delimiter and symbol normalization"),
    "line-number-extractor": ("transitional", "deterministic text rule"),
    "pandoc-code": ("transitional", "docstruct code reflow, in place"),
    "rep-guard": ("transitional", "deterministic text rule"),
    "tailjoin": ("transitional", "docstruct tailjoin"),
    "tailjoin-positioned": ("transitional", "docstruct tailjoin"),
    "unicode-repair": ("transitional", "deterministic text rule"),
    "verse-chunker": ("transitional", "deterministic text rule"),
    "xycut-order": ("transitional", "deterministic layout rule"),
    "agreement-rule": ("transitional", "compares the recorded secondary extraction"),
    "rescue-omitted": ("transitional", "compares the recorded secondary extraction"),
    "skeleton-order": ("transitional", "compares the recorded secondary extraction"),
    "table-smart-fusion": ("transitional", "compares the recorded secondary extraction"),
    # Moved from before planning into the plan (#640, M2); not new work in the
    # core. Its Toolbox calls are optional (METHOD_OPTIONAL_CAPABILITIES).
    "table-enrichment": ("transitional", "reads tables with the DataAgent model; marks cell math"),
    # Moved from before planning into the plan (#640, M1); not new work in
    # the core. Its Toolbox call is optional (METHOD_OPTIONAL_CAPABILITIES).
    "picture-description": ("transitional", "describes pictures with the VisionAgent model"),
    # Moved from before planning into the plan (#640, M3). Its Toolbox calls
    # are optional (METHOD_OPTIONAL_CAPABILITIES).
    "formula-recognizer": ("transitional", "reads formula LaTeX, with the VisionAgent model as fallback"),
    # Moved from before planning into the plan (#640, M4). Its Toolbox call
    # is optional (METHOD_OPTIONAL_CAPABILITIES).
    "formula-region-classifier": ("transitional", "asks the VisionAgent model what a formula region holds"),
    # Moved from before planning and the pass after execution into the plan
    # (#640, M4b): the detection runs in the core (docstruct); its Toolbox
    # call is optional (METHOD_OPTIONAL_CAPABILITIES).
    "inline-math-marker": ("transitional", "finds inline math runs from the text layer's fonts"),
    "vision-description": ("validation", "the picture descriptions picture-description made"),
    "pandoc-table": ("validation", "the table structure table-enrichment produced"),
    "human-review": ("symbolic", "the terminal escalation"),
}

#: Methods with a cost but no handler: never available, so never planned.
NEVER_AVAILABLE_METHODS: dict[str, str] = {
    "table-specialist": "no handler registered (#804)",
}


@dataclass(frozen=True)
class AvailabilityDecision:
    mode: str
    catalog_revision: str | None
    #: Requested methods the catalogue rules out, with the reasons.
    blocked: dict[str, list[str]] = field(default_factory=dict)
    catalog_error: str | None = None
    #: Requested method -> the ``(capability@version, provider)`` pairs it calls.
    requirements: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: The required pairs the snapshot offers; ``None`` offers them all.
    offered: list[tuple[str, str]] | None = None
    #: Requested method -> its optional ``(capability@version, provider)`` pairs (#848).
    optional: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: Requested methods that may run degraded, with the optional calls the
    #: snapshot lacks: per method, not per document (a document may never
    #: make the call). Whatever the mode, they are never ruled out.
    degraded: dict[str, list[str]] = field(default_factory=dict)

    @property
    def enforced(self) -> bool:
        """Whether this decision's snapshot restricted the plan.

        True for ``enforce``, the only mode that reads the catalogue; a plan
        checkpoint from the former ``observe`` mode restores ``False`` so its
        metadata keeps describing what it assumed.
        """
        return self.mode == "enforce"

    @property
    def unavailable_methods(self) -> list[str]:
        """Methods to keep out of the plan by name: none since domain 2.4.

        The catalogue restricts the plan through :meth:`catalogue_facts`. A
        plan checkpoint from before 2.4 still carries its own list.
        """
        return []

    @property
    def offered_source(self) -> str:
        """Where the ``offered`` facts come from.

        ``catalogue_snapshot``: what the snapshot publishes (the default
        mode). ``assumed``: every requirement is offered whatever the snapshot
        says; only a plan checkpoint built under the former ``observe`` mode
        restores this. ``none``: no requirement to offer (``off``, or no
        Toolbox method).
        """
        if not self.requirements:
            return "none"
        return "assumed" if self.offered is None else "catalogue_snapshot"

    @property
    def assumed_runnable(self) -> list[str]:
        """Methods the snapshot rules out that the plan may still use.

        New decisions always take ``offered`` from the snapshot, so this is
        empty. A plan checkpoint built under the former ``observe`` mode keeps
        its assumed facts (``from_metadata``), and this names what it assumed.
        """
        return sorted(self.blocked) if self.offered is None else []

    def catalogue_facts(self) -> CatalogueFacts:
        """The decision as problem facts (domain 2.4)."""
        return CatalogueFacts(
            requirements={method: frozenset(pairs) for method, pairs in self.requirements.items()},
            offered=None if self.offered is None else frozenset(self.offered),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "catalog_revision": self.catalog_revision,
            "catalog_error": self.catalog_error,
            "blocked_methods": self.blocked,
            "applied": self.enforced and bool(self.blocked),
            "requirements": {method: [list(pair) for pair in pairs] for method, pairs in self.requirements.items()},
            "offered": None if self.offered is None else [list(pair) for pair in self.offered],
            "offered_source": self.offered_source,
            "assumed_runnable_methods": self.assumed_runnable,
            "optional": {method: [list(pair) for pair in pairs] for method, pairs in self.optional.items()},
            "degraded_methods": self.degraded,
        }

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any], toolbox: ToolboxConfig) -> AvailabilityDecision:
        """The decision a plan was built under, from its checkpoint.

        A checkpoint without the mode gets the run's (``toolbox``); one from
        before domain 2.4 has no requirements, so its replans add no facts.
        A checkpoint built under the removed ``observe`` mode keeps ``mode``
        and ``offered: null``, so its replans keep offering every requirement
        (see :meth:`catalogue_facts`); deleting the plan checkpoint replans
        under the snapshot.
        """
        offered = metadata.get("offered")
        return cls(
            mode=str(metadata.get("mode") or gate_mode(toolbox)),
            catalog_revision=metadata.get("catalog_revision"),
            blocked=_restored_reasons(metadata.get("blocked_methods")),
            catalog_error=metadata.get("catalog_error"),
            requirements=_restored_pairs(metadata.get("requirements")),
            offered=None if offered is None else [(str(c), str(p)) for c, p in offered],
            # A checkpoint from before #848 has neither: nothing degraded on record.
            optional=_restored_pairs(metadata.get("optional")),
            degraded=_restored_reasons(metadata.get("degraded_methods")),
        )


def _restored_pairs(raw: dict[str, Any] | None) -> dict[str, list[tuple[str, str]]]:
    """Method -> ``(capability, provider)`` pairs, from a checkpoint's JSON."""
    return {
        str(method): [(str(capability), str(provider)) for capability, provider in pairs]
        for method, pairs in (raw or {}).items()
    }


def _restored_reasons(raw: dict[str, Any] | None) -> dict[str, list[str]]:
    """Method -> reasons, from a checkpoint's JSON."""
    return {str(method): [str(reason) for reason in reasons] for method, reasons in (raw or {}).items()}


def capability_ref(capability_id: str) -> str:
    """``capability_id@version``: the capability at the exact contract version
    the SDK client calls, the version the catalogue check requires (#640).

    A capability outside the SDK allowlist has no version to bind; it keeps its
    bare id, and the check rules it out anyway.
    """
    spec = TOOLBOX_CAPABILITIES.get(capability_id)
    return capability_id if spec is None else f"{capability_id}@{spec.contract_version}"


def gate_mode(toolbox: ToolboxConfig) -> str:
    """``toolbox.availability_gate``, or ``enforce`` for a value it does not know.

    The value is normalised (surrounding whitespace and case), so ``Off`` from
    a direct ``CoreConfig`` caller still means ``off``. ``observe`` was removed
    (#809): a deployment still configured with it gets the default mode, so the
    snapshot becomes the input. :func:`decide` warns once per unknown value;
    the fallback keeps a typo from silently disabling the fail-closed check.
    """
    mode = toolbox.availability_gate.strip().lower()
    return mode if mode in GATE_MODES else "enforce"


#: Raw gate values already reported, so a typo warns once per process instead
#: of on every document.
_WARNED_GATE_MODES: set[str] = set()


def _warn_unknown_gate_mode(raw: str) -> None:
    value = raw.strip().lower()
    if value in GATE_MODES or value in _WARNED_GATE_MODES:
        return
    _WARNED_GATE_MODES.add(value)
    if value == "observe":
        logger.warning(
            "TOOLBOX_AVAILABILITY_GATE=observe was removed (#809); using enforce"
        )
    else:
        logger.warning(
            "TOOLBOX_AVAILABILITY_GATE={!r} is not a known mode ({}); using enforce",
            raw,
            ", ".join(GATE_MODES),
        )


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
    """Which of ``methods`` cannot run against ``snapshot``, with ``config``'s
    providers, and which may run degraded (#848).

    ``mode`` is recorded in the decision and its metadata; the snapshot always
    decides what is offered. ``off`` is handled by :func:`decide`, which never
    calls this function: a caller that asks :func:`evaluate` for ``off`` would
    get catalogue facts the mode promises not to use, so it is refused.
    """
    # Read once: both passes below go over it, and a generator would leave
    # the second empty (#856 review).
    methods = sorted(set(methods))
    mode = mode.strip().lower()
    if mode == "off":
        raise ValueError("evaluate() does not handle the off mode; use decide()")
    # A caller that names the removed ``observe`` asks for the default: the
    # snapshot decides.
    mode = mode if mode in GATE_MODES else "enforce"
    blocked: dict[str, list[str]] = {}
    required: dict[str, list[tuple[str, str]]] = {}
    offered: set[tuple[str, str]] = set()
    optional, degraded = _optional_calls(methods, snapshot, config)
    for method in methods:
        requirements = METHOD_TOOLBOX_REQUIREMENTS.get(method)
        if requirements is None:
            continue
        needed = requirements(config)
        required[method] = sorted({(capability_ref(item.capability_id), item.provider) for item in needed})
        offered.update(
            (capability_ref(item.capability_id), item.provider)
            for item in needed
            if not missing_requirements(snapshot, [item])
        )
        reasons = missing_requirements(snapshot, needed)
        if reasons:
            blocked[method] = reasons
    return AvailabilityDecision(
        mode=mode,
        catalog_revision=snapshot.revision if snapshot else None,
        blocked=blocked,
        catalog_error=catalog_error if snapshot is None else None,
        requirements=required,
        # The snapshot is the input: it decides what is offered.
        offered=sorted(offered),
        optional=optional,
        degraded=degraded,
    )


def _optional_calls(
    methods: Iterable[str], snapshot: CatalogSnapshot | None, config: CoreConfig
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[str]]]:
    """Each requested method's optional calls, and the ones ``snapshot``
    lacks. Without a snapshot nothing is known, so nothing is reported
    degraded: the decision's ``catalog_error`` already says why."""
    optional: dict[str, list[tuple[str, str]]] = {}
    degraded: dict[str, list[str]] = {}
    for method in sorted(set(methods)):
        calls = METHOD_OPTIONAL_CAPABILITIES.get(method)
        if calls is None:
            continue
        wanted = calls(config)
        optional[method] = sorted({(capability_ref(item.capability_id), item.provider) for item in wanted})
        if snapshot is not None and (reasons := missing_requirements(snapshot, wanted)):
            degraded[method] = reasons
    return optional, degraded


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
    _warn_unknown_gate_mode(config.toolbox.availability_gate)
    mode = gate_mode(config.toolbox)
    methods = requested_methods(manifest)
    if mode == "off" or not methods & (set(METHOD_TOOLBOX_REQUIREMENTS) | set(METHOD_OPTIONAL_CAPABILITIES)):
        return AvailabilityDecision(mode=mode, catalog_revision=None)
    cache = catalog_cache(config.toolbox)
    snapshot = await cache.get()
    return evaluate(
        methods, snapshot, mode=mode, config=config, catalog_error=cache.last_error
    )


__all__ = [
    "LOCAL_METHODS",
    "LOCAL_ROLES",
    "METHOD_OPTIONAL_CAPABILITIES",
    "METHOD_TOOLBOX_REQUIREMENTS",
    "NEVER_AVAILABLE_METHODS",
    "AvailabilityDecision",
    "catalog_cache",
    "decide",
    "capability_ref",
    "evaluate",
    "gate_mode",
    "requested_methods",
]
