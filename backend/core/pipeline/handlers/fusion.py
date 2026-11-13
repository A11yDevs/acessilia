"""Deterministic handlers for the providers' extraction: fusing, choosing or confirming it.

``dual-provider-fusion`` runs both providers and fuses their extraction
(``backend.pipeline.fusion.extract_fused``), reusing a fusion already recorded
for the same source. ``single-provider`` is the other method for
``fuse-providers``; it chooses nothing, and only checks that the manifest
already carries the configured provider's extraction.

``table-smart-fusion`` and ``agreement-rule`` choose between the two providers
of ``FUSION_MODE=dual``; they port Dr.DocBench rules (tree_differ_v2.py of the
drbench-2026-snapshot tag and docstruct.fusion.adjudication.decide_v1). They
read the secondary provider's extraction (``backend.core.pipeline.secondary``).
The rules were calibrated on the docling + mineru pair, so any other pair fails
explicitly.

Moved from the PDDL orchestrator (#402, phase 3, step 6): the code verbatim,
with the two docstrings of the dual-provider fusion translated from Portuguese.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    Artifact,
    ManifestElement,
    PageDescriptor,
    ProcessingManifest,
)
from backend.core.pipeline.elements import (
    _element_bbox,
)
from backend.core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from backend.core.pipeline.handlers.messages import (
    MSG_DUAL_FUSION_DONE,
    MSG_DUAL_FUSION_FAILED,
    MSG_DUAL_FUSION_SINGLE_PROVIDER,
    MSG_DUAL_FUSION_UNSUCCESSFUL,
    MSG_ROUTER_NO_PAGE,
    MSG_ROUTER_PRIMARY,
    MSG_ROUTER_SECONDARY,
    MSG_SINGLE_PROVIDER_ONLY,
    MSG_TABLE_SOURCE,
)
from backend.core.pipeline.secondary import (
    _CALIBRATED_PAIR,
    _page_markdown,
    _pair_block,
    _secondary_or_failure,
)
from backend.core.pipeline.toolbox import (
    _source_artifact_id,
)
from backend.i18n import t


#: Accepted Dr.DocBench table preference (TEDS): MinerU's table, unless Docling's
#: has spans or is the only one.
_TABLE_PREFERENCE = "mineru"


def _handle_table_smart_fusion_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pick each table's source between the two providers (Dr.DocBench rule).

    Docling's table is kept when it has spans (MinerU flattens them) or when it
    is the only one; otherwise MinerU's table is adopted. Tables are paired by
    position or text; a page with a single table on each side pairs them only
    when there is no position to compare. The choice and its reason are recorded
    in ``table_source`` / ``table_source_reason``.
    """
    from docstruct.tables.ast import analyze_table_complexity

    tables = [
        element
        for element in _target_elements(manifest, obligation_id)
        if element.type == "table"
    ]
    if not tables:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name, secondary_name = _CALIBRATED_PAIR
    primary_tables_by_page = Counter(
        element.page_number
        for element in manifest.elements
        if element.type == "table"
    )
    reasons: Counter = Counter()
    for element in tables:
        primary_ast = (element.metadata or {}).get("table_ast")
        candidates = [
            block
            for block in secondary.pages.get(element.page_number or 0, [])
            if block.get("type") == "table"
        ]
        match = _pair_block(element, manifest, candidates, secondary, set())
        if (
            match is None
            and len(candidates) == 1
            and primary_tables_by_page[element.page_number] == 1
            and (
                _element_bbox(element, manifest) is None
                or secondary.bbox(candidates[0]) is None
            )
        ):
            # One table on each side and no position to compare them by: the
            # same table. With both positions known and no overlap, they are not.
            match = 0
        chosen = candidates[match] if match is not None else None
        chosen_meta = (chosen or {}).get("metadata") or {}

        if primary_ast and analyze_table_complexity(primary_ast).has_spans:
            source, reason = primary_name, "primary-has-spans"
        elif not candidates:
            source, reason = primary_name, "no-secondary-table"
        elif chosen is None:
            source, reason = primary_name, "no-secondary-match"
        elif not (chosen.get("text") or chosen_meta.get("table_ast")):
            source, reason = primary_name, "secondary-table-empty"
        else:
            source, reason = _TABLE_PREFERENCE, f"preference-{_TABLE_PREFERENCE}"

        if source == secondary_name and chosen is not None:
            # Docling's table_* keys (AST, row/column counts, header) describe
            # the table being replaced; the output prefers table_ast over the
            # text, so a stale AST would hide the adopted MinerU text.
            for key in [k for k in element.metadata if k.startswith("table_")]:
                del element.metadata[key]
            if chosen.get("text"):
                element.text = chosen["text"]
            for key, value in chosen_meta.items():
                if key.startswith("table_"):
                    element.metadata[key] = value
        element.metadata["table_source"] = source
        element.metadata["table_source_reason"] = reason
        reasons[reason] += 1

    return MethodResult(
        success=True,
        validated=True,
        message=t(MSG_TABLE_SOURCE).format(
            reasons=", ".join(
                f"{reason}={count}" for reason, count in sorted(reasons.items())
            )
        ),
    )


def _handle_agreement_rule_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Deterministic page router between the providers (``decide_v1``).

    When the router keeps the primary (Docling) page the obligation is
    satisfied without changing the text. When it picks the secondary page the
    decision is recorded but not applied: replacing a whole page would reopen
    the manifest mid-plan, and Dr.DocBench measured this router below the
    block-level fusion the core already runs. The method then fails, so the
    obligation goes to ``human-review`` with the route in ``page_route``.
    """
    from docstruct.fusion.adjudication import decide_v1

    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name = _CALIBRATED_PAIR[0]
    routes: dict[int, tuple[str, str]] = {}
    for page_number in sorted({e.page_number for e in elements if e.page_number}):
        primary_md = _page_markdown(
            (element.type, element.text)
            for element in sorted(manifest.elements, key=lambda e: e.reading_order)
            if element.page_number == page_number
        )
        secondary_md = _page_markdown(
            (str(block.get("type") or ""), block.get("text"))
            for block in secondary.pages.get(page_number, [])
        )
        routes[page_number] = decide_v1(primary_md, secondary_md)

    for element in elements:
        if element.page_number in routes:
            choice, reason = routes[element.page_number]
            element.metadata["page_route"] = {"choice": choice, "reason": reason}

    rerouted = {page: route for page, route in routes.items() if route[0] != primary_name}
    if not routes:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_ROUTER_NO_PAGE),
        )
    if rerouted:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_ROUTER_SECONDARY).format(
                routes=", ".join(
                    f"p{page}: {reason}"
                    for page, (_, reason) in sorted(rerouted.items())
                )
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=t(MSG_ROUTER_PRIMARY).format(
            pages=", ".join(map(str, sorted(routes)))
        ),
    )


def _handle_single_provider_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Satisfy ``fuse-providers`` with the extraction the manifest already carries.

    There is nothing to re-run: the manifest's elements are the configured
    provider's extraction, with the pages the deterministic router took from
    the secondary provider in dual mode (``fusion.apply_page_routes``). The
    method does not claim a single-provider document; it checks only that the
    manifest was extracted by the configured provider and has content. It used
    to extract the whole document again, uploaded anew and with the Toolbox
    cache off, once per ``fuse-providers`` step, and changed nothing in the
    manifest: a full extraction of cost for no content.
    """
    from backend.config.settings import settings

    obligation = next(
        (item for item in manifest.obligations if item.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)
    if obligation.kind != "fuse-providers":
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_SINGLE_PROVIDER_ONLY),
        )

    provider = str(manifest.extractor.configuration.get("toolbox_provider") or "")
    if not provider:
        return MethodResult(
            success=False,
            validated=False,
            message="The manifest does not record the provider it was extracted by",
        )
    if provider != settings.toolbox_provider:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"The manifest was extracted by {provider}, not by the configured "
                f"provider ({settings.toolbox_provider})"
            ),
        )
    if not manifest.elements:
        return MethodResult(
            success=False,
            validated=False,
            message="The manifest extraction has no elements",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=(
            f"The manifest already carries the extraction ({provider}); "
            "nothing to re-extract"
        ),
    )


def _run_extract_fused(
    source_path: Path, *, artifact_id: str | None = None, policy=None
) -> dict:
    """Run ``extract_fused`` in a way that suits the current event loop.

    Checks for a running event loop **before** creating the coroutine, so no
    coroutine object is left without an ``await`` (which would raise
    ``RuntimeWarning: coroutine ... was never awaited``).

    Architecture note: when called from a thread with a running event loop
    (Agno Workflow, API), ``.result()`` still blocks the calling loop until the
    fusion ends. The handlers' contract stays synchronous; code that calls the
    executor from async code must run the whole executor with
    ``await run_blocking(...)`` so as not to block the main event loop.
    """
    import concurrent.futures

    from backend.pipeline.fusion import extract_fused

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Synchronous context (deterministic executor, CLI, tests): no event
        # loop is running in this thread.
        return asyncio.run(extract_fused(source_path, artifact_id=artifact_id, policy=policy))

    # An event loop is already running in this thread; since the handler is
    # synchronous, the coroutine runs in a dedicated thread with its own loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            lambda: asyncio.run(
                extract_fused(source_path, artifact_id=artifact_id, policy=policy)
            )
        ).result()


def _reusable_fusion_payload(manifest: ProcessingManifest) -> dict | None:
    from dataclasses import asdict

    from docstruct.policy import FusionPolicy

    from backend.services.cache import processing_cache_configuration

    ref = manifest.extractor.configuration.get("fusion_reuse") or {}
    try:
        content = Path(ref["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != ref["sha256"]:
            return None
        record = json.loads(content)
        if record["source_sha256"] != manifest.source.sha256:
            return None
        expected_policy = manifest.extractor.configuration.get("fusion_policy")
        if expected_policy is None:
            expected_policy = asdict(FusionPolicy())
        if record.get("policy") != expected_policy:
            return None
        if json.dumps(record["configuration"], sort_keys=True) != json.dumps(processing_cache_configuration(), sort_keys=True):
            return None
        payload = record["payload"]
        return payload if isinstance(payload, dict) else None
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _handle_dual_provider_fusion_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Fuse two providers (docling+mineru) for the target obligation.

    Reuses ``backend.pipeline.fusion.extract_fused`` (phase 4) to produce the
    fused payload, writes the JSON to ``data_dir/artifacts/fusion/`` and returns
    it in ``MethodResult.artifacts``, leaving the ``ExecutorAgent`` to fold it
    into the manifest and record the provenance on the attempt.

    In single mode (FUSION_MODE=single) the method is not admissible and the
    compiler must not select it.

    Reuses the initial fusion when the hash, the document and the configuration
    match. Missing, corrupt or incompatible evidence triggers a new dual
    extraction.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)
    source_path = Path(manifest.source.path)
    # Reuse the document the structure extractor already stored in the Toolbox.
    artifact_id = _source_artifact_id(manifest)
    try:
        payload = _reusable_fusion_payload(manifest)
        if payload is None:
            from docstruct.policy import FusionPolicy

            policy_config = manifest.extractor.configuration.get("fusion_policy")
            policy = FusionPolicy.from_dict(policy_config) if policy_config else None
            if policy is None:
                payload = _run_extract_fused(source_path, artifact_id=artifact_id)
            else:
                payload = _run_extract_fused(source_path, artifact_id=artifact_id, policy=policy)
    except Exception as exc:  # noqa: BLE001
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_DUAL_FUSION_FAILED).format(
                error_type=type(exc).__name__, error=exc
            ),
        )
    if payload.get("status") != "succeeded":
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_DUAL_FUSION_UNSUCCESSFUL),
        )

    # The planned action is dual-provider: if only one provider took part, the
    # planned semantics did not run, so the method fails to allow replanning
    # to a single-provider method.
    provider = str(payload.get("provider") or "")
    if "+" not in provider:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_DUAL_FUSION_SINGLE_PROVIDER).format(
                provider=provider or "unknown"
            ),
        )

    try:
        elements = _fused_text_elements(manifest, obligation.target_ids, payload)
    except (TypeError, ValueError) as exc:
        return MethodResult(success=False, validated=False, message=str(exc))

    artifact = _persist_fusion_payload(
        manifest,
        payload,
        obligation_id,
        kind="fusion-payload",
    )

    manifest.elements = elements
    page_ids = {element.page_number or 1 for element in elements}
    existing_pages = {page.page_number: page for page in manifest.pages}
    manifest.pages = [
        PageDescriptor(
            page_number=number,
            width=existing_pages[number].width if number in existing_pages else None,
            height=existing_pages[number].height if number in existing_pages else None,
            element_ids=[element.id for element in elements if (element.page_number or 1) == number],
        )
        for number in sorted(page_ids)
    ]
    manifest.summary.page_count = len(manifest.pages)
    manifest.summary.element_count = len(elements)
    manifest.summary.element_types = dict(Counter(element.type for element in elements))
    return MethodResult(
        success=True,
        validated=True,
        message=t(MSG_DUAL_FUSION_DONE),
        artifacts=[artifact],
    )


def _fused_text_elements(
    manifest: ProcessingManifest, target_ids: list[str], payload: dict[str, Any]
) -> list[ManifestElement]:
    # The fusion adapter currently emits text-only blocks. It cannot safely
    # replace a structured document or a subset with a whole-document result.
    if any(element.type != "paragraph" for element in manifest.elements) or set(target_ids) != {
        element.id for element in manifest.elements
    }:
        raise ValueError("Text fusion requires all paragraphs of a text-only manifest")
    raw_elements = payload.get("document", {}).get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        raise ValueError("Fusion returned no usable document elements")
    originals = sorted(manifest.elements, key=lambda element: element.reading_order)
    by_page: dict[int, list[dict[str, Any]]] = {}
    for raw in raw_elements:
        if not isinstance(raw, dict) or raw.get("type") != "paragraph":
            raise ValueError("Fusion returned unsupported structured content")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Fusion returned an empty text block")
        page = raw.get("page_number", raw.get("page"))
        if page is None:
            if len(manifest.pages) > 1:
                raise ValueError("Fusion omitted page identity for a multipage document")
            page = manifest.pages[0].page_number if manifest.pages else 1
        if type(page) is not int or page < 1:
            raise ValueError("Fusion returned an invalid page number")
        by_page.setdefault(page, []).append(raw)
    original_pages = {element.page_number or 1 for element in originals}
    if not original_pages.issubset(by_page):
        raise ValueError("Fusion omitted a source page")

    result = []
    for number, rows in sorted(by_page.items()):
        old = [element for element in originals if (element.page_number or 1) == number]
        # Keep every existing ID and reference; ambiguous mappings fail closed.
        if len(rows) < len(old):
            raise ValueError("Fusion cannot safely map fewer blocks to existing element references")
        for index, raw in enumerate(rows):
            if index < len(old):
                element = old[index].model_copy(deep=True)
                element.text = raw["text"]
                element.page_number = number
            else:
                identifier = hashlib.sha256(json.dumps([
                    manifest.manifest_id, number, index, raw["text"],
                ]).encode()).hexdigest()[:24]
                element = ManifestElement(
                    id=f"element-fusion-{identifier}", type="paragraph", raw_label="paragraph",
                    reading_order=len(result) + 1, hierarchy_level=0,
                    page_number=number, text=raw["text"],
                )
            element.metadata["fusion_provider"] = payload["provider"]
            element.reading_order = len(result) + 1
            result.append(element)
    return result


def _persist_fusion_payload(
    manifest: ProcessingManifest,
    payload: dict[str, Any],
    obligation_id: str,
    *,
    kind: str,
) -> Artifact:
    """Write the payload atomically, addressed by its manifest scope and content."""
    from backend.config.settings import settings

    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    scope = hashlib.sha256(json.dumps([
        manifest.manifest_id, manifest.source.document_id, manifest.source.sha256,
        manifest.revision, obligation_id,
    ]).encode()).hexdigest()
    output_path = settings.data_dir / "artifacts" / "fusion" / scope / f"{digest}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return Artifact(
        id=f"artifact-{kind.removesuffix('-payload')}-{scope[:16]}-{digest[:16]}",
        kind=kind,
        path=str(output_path),
        media_type="application/json",
        sha256=digest,
    )
