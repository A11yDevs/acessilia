"""Deterministic handlers for the providers' extraction: choosing or confirming it.

``table-smart-fusion`` and ``agreement-rule`` choose between the two providers
of ``FUSION_MODE=dual``; they port Dr.DocBench rules
(tree_differ_v2.py of the drbench-2026-snapshot tag and
docstruct.fusion.adjudication.decide_v1). They read the secondary provider's
extraction (``backend.core.pipeline.secondary``). The rules were calibrated on
the docling + mineru pair, so any other pair fails explicitly.
``single-provider`` chooses nothing: it satisfies ``fuse-providers`` by checking
that the manifest already carries the configured provider's extraction. Moved verbatim from the PDDL orchestrator (#402,
phase 3, step 6).
"""

from __future__ import annotations

from collections import Counter

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.core.pipeline.elements import (
    _element_bbox,
)
from backend.core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from backend.core.pipeline.secondary import (
    _CALIBRATED_PAIR,
    _page_markdown,
    _pair_block,
    _secondary_or_failure,
)


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
        message="Fonte de tabela escolhida: "
        + ", ".join(f"{reason}={count}" for reason, count in sorted(reasons.items())),
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
            message="Obrigação sem página identificada para o roteador",
        )
    if rerouted:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Roteador por página escolhe o provider secundário ("
                + ", ".join(f"p{page}: {reason}" for page, (_, reason) in sorted(rerouted.items()))
                + "); a troca de página não é aplicada automaticamente"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message="Roteador por página mantém o provider primário nas páginas "
        + ", ".join(map(str, sorted(routes))),
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
            message="single-provider só é válido para fuse-providers",
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
