from __future__ import annotations

import hashlib
import mimetypes
import re
from collections import Counter
from pathlib import Path
from typing import Any

from backend.i18n import t
from backend.log_messages import (
    MSG_HEADING_GAP,
    MSG_OBLIGATION_CODE,
    MSG_OBLIGATION_FORMULA,
    MSG_OBLIGATION_IMAGE,
    MSG_OBLIGATION_TABLE,
    MSG_OBLIGATION_UNKNOWN,
)
from backend.pipeline.sanitizer import sanitize_text
from backend.pipeline.table_ast import normalize_table_ast
from backend.pipeline.table_ast import rows_from_table_ast

from backend.core.manifest.models import (
    BoundingBox,
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    Observation,
    PageDescriptor,
    ProcessingManifest,
    Provenance,
    SourceDocument,
)


LABEL_TO_TYPE = {
    "title": "title",
    "section_header": "heading",
    "heading": "heading",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list_item": "list_item",
    "table": "table",
    "picture": "picture",
    "image": "picture",
    "formula": "formula",
    "equation": "formula",
    "code": "code",
    "caption": "caption",
    "footnote": "footnote",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "checkbox_selected": "checkbox",
    "checkbox_unselected": "checkbox",
    "key_value_region": "key_value",
    "form": "form",
}

OBLIGATION_BY_TYPE = {
    "picture": (
        "describe-image",
        t(MSG_OBLIGATION_IMAGE),
        ["vision-description", "human-review"],
    ),
    "table": (
        "linearize-table",
        t(MSG_OBLIGATION_TABLE),
        ["pandoc-table", "human-review"],
    ),
    "formula": (
        "verbalize-formula",
        t(MSG_OBLIGATION_FORMULA),
        ["mathml", "latex-verbalizer", "human-review"],
    ),
    "code": (
        "preserve-code-semantics",
        t(MSG_OBLIGATION_CODE),
        ["pandoc-code", "human-review"],
    ),
    "unknown": (
        "review-structure",
        t(MSG_OBLIGATION_UNKNOWN),
        ["pymupdf-region", "human-review"],
    ),
}

DEFAULT_METHOD_COSTS = {
    "vision-description": 20,
    "pandoc-table": 15,
    "mathml": 10,
    "latex-verbalizer": 20,
    "pandoc-code": 10,
    "pymupdf-region": 30,
    "deterministic-heading-repair": 5,
    "human-review": 100,
    # --- Capacidades da PR #125 (domínio v2.3) ---
    # Determinísticas: custo baixo, o planner deve preferi-las.
    "agreement-rule": 5,
    "xycut-order": 10,
    "skeleton-order": 5,
    "latex-normalizer": 10,
    "rep-guard": 5,
    "tailjoin": 5,
    "tailjoin-positioned": 5,
    "verse-chunker": 5,
    "line-number-extractor": 5,
    "norm-fix": 5,
    "rescue-omitted": 15,
    "table-smart-fusion": 20,
    "single-provider": 20,
    # Consomem modelo: custo alto, só admissíveis com a política ativa.
    "vlm-pairwise-judge": 40,
    "table-specialist": 45,
    "dual-provider-fusion": 60,
}

# Obrigações introduzidas na versão 2.3 do domínio PDDL (PR #125).
# kind -> (rationale, métodos admissíveis)
V23_OBLIGATION_BY_KIND = {
    "adjudicate-page": (
        "Página com divergência entre providers exige adjudicação.",
        ["vlm-pairwise-judge", "agreement-rule", "human-review"],
    ),
    "fuse-providers": (
        "Extração fundida de dois providers melhora a fidelidade do texto.",
        ["dual-provider-fusion", "single-provider", "human-review"],
    ),
    "refine-reading-order": (
        "Ordem de leitura precisa seguir as colunas da página.",
        ["xycut-order", "skeleton-order", "human-review"],
    ),
    "normalize-formula": (
        "Fórmula exige normalização de delimitadores e símbolos.",
        ["latex-normalizer", "mathml", "human-review"],
    ),
    "rescue-omitted-block": (
        "Bloco presente em um provider foi omitido na fusão.",
        ["rescue-omitted", "human-review"],
    ),
    "guard-repetition": (
        "Saída degenerada por repetição precisa ser cortada.",
        ["rep-guard", "human-review"],
    ),
    "join-tail-blocks": (
        "Blocos curtos finais (cabeçalho/rodapé/número) devem ser unidos.",
        ["tailjoin-positioned", "tailjoin", "human-review"],
    ),
    "select-table-source": (
        "Tabela exige escolha da melhor fonte entre os providers.",
        ["table-smart-fusion", "table-specialist", "human-review"],
    ),
    "chunk-verse": (
        "Bloco de verso/registro excede o limite de reagrupamento do avaliador.",
        ["verse-chunker", "human-review"],
    ),
    "extract-line-numbers": (
        "Números de linha marginais devem virar blocos próprios.",
        ["line-number-extractor", "human-review"],
    ),
    "normalize-text": (
        "Texto exige limpezas determinísticas (ligaduras, hífen, NBSP).",
        ["norm-fix", "human-review"],
    ),
}

CALL_OUT_MIN_GROUP_SIZE = 3
CALL_OUT_MIN_INDENT_PX = 8.0
CALL_OUT_MIN_INDENT_RATIO = 0.015
CALL_OUT_MAX_WIDTH_RATIO = 0.9
CALL_OUT_MAX_VERTICAL_GAP = 28.0
KNOWN_CALLOUT_TITLES = {
    "precisamos mesmo de outra classe?",
    "super e sub classe",
}


def build_processing_manifest(
    source_path: Path,
    extraction: Any,
    *,
    language: str = "pt-BR",
    refine_reading_order: bool = False,
) -> ProcessingManifest:
    source_path = source_path.resolve()
    digest = _sha256(source_path)

    # ── Toolbox extraction: manifest JSON já veio pronto ──────────────────
    if isinstance(extraction.document, dict):
        return _build_from_toolbox_json(
            source_path,
            extraction,
            digest=digest,
            language=language,
            refine_reading_order=refine_reading_order,
        )

    # ── Docling extraction: construir a partir do objeto docling.Document ──
    extractor_name = str(extraction.configuration.get("extractor", "")).strip().lower()
    enable_callouts = extractor_name != "pymupdf"
    elements = _build_elements(extraction.document, enable_callouts=enable_callouts)
    if refine_reading_order:
        elements = _refine_reading_order(elements)
    pages = _build_pages(extraction.document, elements)
    title = _infer_title(source_path, elements)
    observations, obligations = _derive_processing_needs(elements)
    v23_observations, v23_obligations = _derive_v23_processing_needs(
        elements,
        page_sizes={
            page.page_number: (page.width, page.height) for page in pages
        },
        fusion_evidence=getattr(extraction, "fusion_evidence", None),
        fusion_stats=getattr(extraction, "fusion_stats", None),
    )
    observations.extend(v23_observations)
    obligations.extend(v23_obligations)
    element_types = dict(sorted(Counter(e.type for e in elements).items()))

    source = SourceDocument(
        document_id=f"doc-{digest[:16]}",
        filename=source_path.name,
        path=str(source_path),
        media_type=mimetypes.guess_type(source_path.name)[0]
        or "application/octet-stream",
        byte_size=source_path.stat().st_size,
        sha256=digest,
    )
    extractor = ExtractorRun(
        version=extraction.version,
        started_at=extraction.started_at,
        completed_at=extraction.completed_at,
        duration_ms=extraction.duration_ms,
        configuration=extraction.configuration,
    )
    return ProcessingManifest(
        manifest_id=f"manifest-{digest[:16]}-r1",
        created_at=extraction.completed_at,
        source=source,
        extractor=extractor,
        title=title,
        language=language,
        pages=pages,
        elements=elements,
        observations=observations,
        obligations=obligations,
        summary=ManifestSummary(
            page_count=len(pages),
            element_count=len(elements),
            observation_count=len(observations),
            obligation_count=len(obligations),
            element_types=element_types,
        ),
    )


def _build_from_toolbox_json(
    source_path: Path,
    extraction: Any,
    *,
    digest: str,
    language: str,
    refine_reading_order: bool = False,
) -> ProcessingManifest:
    """Build a ProcessingManifest from a pre-built Toolbox JSON response.

    The Toolbox already returns a complete ProcessingManifest-compatible JSON
    payload inside ``extraction.document["document"]``, so we parse it directly.
    """
    data: dict[str, Any] = extraction.document["document"]

    data["manifest_id"] = data.get("manifest_id") or f"manifest-{digest[:16]}-r1"

    # Override source with local file info
    data["source"] = {
        "document_id": f"doc-{digest[:16]}",
        "filename": source_path.name,
        "path": str(source_path.resolve()),
        "media_type": mimetypes.guess_type(source_path.name)[0]
        or "application/octet-stream",
        "byte_size": source_path.stat().st_size,
        "sha256": digest,
    }

    # Override extractor metadata with this run
    data["extractor"] = {
        "version": extraction.version,
        "started_at": extraction.started_at.isoformat(),
        "completed_at": extraction.completed_at.isoformat(),
        "duration_ms": extraction.duration_ms,
        "configuration": extraction.configuration,
    }

    data.setdefault("language", language)
    data.setdefault("created_at", extraction.completed_at.isoformat())

    # The Toolbox is a capability layer: deciding what a document needs and which
    # methods may satisfy it is this core's planning policy. Whatever processing
    # needs the payload carries (older Toolbox images derive their own, with
    # methods the core does not implement) are discarded and derived below with
    # the same rules as the Docling path.
    data["observations"] = []
    data["obligations"] = []
    if isinstance(data.get("summary"), dict):
        data["summary"] = {
            **data["summary"],
            "observation_count": 0,
            "obligation_count": 0,
        }

    manifest = ProcessingManifest.model_validate(data)
    if refine_reading_order:
        manifest.elements = _refine_reading_order(manifest.elements)
        by_page: dict[int, list[str]] = {}
        for elem in manifest.elements:
            if elem.page_number is not None:
                by_page.setdefault(elem.page_number, []).append(elem.id)
        for page in manifest.pages:
            page.element_ids = by_page.get(page.page_number, [])
    observations, obligations = _derive_processing_needs(manifest.elements)
    v23_observations, v23_obligations = _derive_v23_processing_needs(
        manifest.elements,
        page_sizes={
            page.page_number: (page.width, page.height) for page in manifest.pages
        },
        fusion_evidence=extraction.document.get("fusion_evidence"),
        fusion_stats=extraction.document.get("fusion_stats"),
    )
    observations.extend(v23_observations)
    obligations.extend(v23_obligations)
    _append_processing_needs(manifest, observations, obligations)
    return manifest


def _build_elements(document: Any, *, enable_callouts: bool = True) -> list[ManifestElement]:
    elements: list[ManifestElement] = []
    try:
        iterator = document.iterate_items(with_groups=True, traverse_pictures=True)
    except TypeError:
        iterator = document.iterate_items(with_groups=True)

    for reading_order, (item, tree_level) in enumerate(iterator, start=1):
        raw_label = _item_label(item)
        element_type = LABEL_TO_TYPE.get(raw_label, _fallback_type(item, raw_label))
        provenance = _provenance(item)
        page_number = provenance[0].page_number if provenance else None
        hierarchy_level = _hierarchy_level(item, element_type, tree_level)
        metadata = _safe_metadata(item, element_type=element_type)
        elements.append(
            ManifestElement(
                id=f"element-{reading_order:06d}",
                type=element_type,
                raw_label=raw_label,
                reading_order=reading_order,
                hierarchy_level=hierarchy_level,
                text=_item_text(item, element_type),
                source_ref=_reference(getattr(item, "self_ref", None)),
                parent_ref=_reference(getattr(item, "parent", None)),
                page_number=page_number,
                confidence=_confidence(item),
                provenance=provenance,
                metadata=metadata,
            )
        )
    by_source_ref = {
        element.source_ref: element.id
        for element in elements
        if element.source_ref is not None
    }
    for element in elements:
        if element.parent_ref is not None:
            element.parent_id = by_source_ref.get(element.parent_ref)
    if enable_callouts:
        _normalize_callout_groups(elements)
    return elements


def _normalize_callout_groups(elements: list[ManifestElement]) -> None:
    by_page: dict[int, list[ManifestElement]] = {}
    for element in elements:
        if element.page_number is None:
            continue
        by_page.setdefault(element.page_number, []).append(element)

    for page_elements in by_page.values():
        _normalize_page_callouts(page_elements)


def _normalize_page_callouts(page_elements: list[ManifestElement]) -> None:
    _tag_known_title_callouts(page_elements)

    text_like = [
        element
        for element in page_elements
        if element.type in {"heading", "paragraph", "list_item", "group", "unknown"}
        and _element_bbox(element) is not None
        and (element.text or "").strip()
        and not element.metadata.get("callout_id")
    ]
    if len(text_like) < CALL_OUT_MIN_GROUP_SIZE:
        return

    main_left, main_right = _estimate_main_text_band(text_like)
    if main_right <= main_left:
        return

    band_width = main_right - main_left
    indent_threshold = max(CALL_OUT_MIN_INDENT_PX, band_width * CALL_OUT_MIN_INDENT_RATIO)

    candidates: list[ManifestElement] = []
    for element in sorted(text_like, key=lambda item: item.reading_order):
        bbox = _element_bbox(element)
        if bbox is None:
            continue
        left, top, right, bottom = bbox
        width = max(1.0, right - left)
        left_indent = left - main_left
        right_indent = main_right - right

        combined_indent = max(0.0, left_indent) + max(0.0, right_indent)
        if (
            max(left_indent, right_indent) < indent_threshold
            and combined_indent < (indent_threshold * 1.35)
        ):
            continue
        if width > band_width * CALL_OUT_MAX_WIDTH_RATIO:
            continue
        if top >= bottom:
            continue
        candidates.append(element)

    if len(candidates) < CALL_OUT_MIN_GROUP_SIZE:
        return

    groups: list[list[ManifestElement]] = []
    current: list[ManifestElement] = [candidates[0]]
    for element in candidates[1:]:
        prev = current[-1]
        if _is_same_callout_cluster(prev, element):
            current.append(element)
        else:
            groups.append(current)
            current = [element]
    groups.append(current)

    for group_index, group in enumerate(groups, start=1):
        if len(group) < CALL_OUT_MIN_GROUP_SIZE:
            continue
        title = group[0]
        if not _is_callout_title_candidate(title):
            continue
        body_count = sum(
            1
            for item in group[1:]
            if item.type in {"paragraph", "list_item", "group", "unknown"}
            and (item.text or "").strip()
        )
        min_body_count = 1 if _is_known_callout_title(title.text or "") else 2
        if body_count < min_body_count:
            continue

        _apply_callout_group(title, group, callout_id=f"callout-p{title.page_number}-g{group_index}")


def _tag_known_title_callouts(page_elements: list[ManifestElement]) -> None:
    ordered = sorted(page_elements, key=lambda item: item.reading_order)
    main_left, main_right = _estimate_main_text_band(ordered)
    band_width = max(0.0, main_right - main_left)
    indent_threshold = max(CALL_OUT_MIN_INDENT_PX, band_width * CALL_OUT_MIN_INDENT_RATIO)
    anchor_count = 0
    for index, title in enumerate(ordered):
        if title.metadata.get("callout_id"):
            continue
        if not _is_known_callout_title(title.text or ""):
            continue
        title_bbox = _element_bbox(title)
        if title_bbox is None:
            continue

        group: list[ManifestElement] = [title]
        previous = title
        for candidate in ordered[index + 1 :]:
            if candidate.metadata.get("callout_id"):
                continue
            if candidate.type in {"heading", "title"} and not _is_known_callout_title(candidate.text or ""):
                break
            if candidate.type not in {"paragraph", "list_item", "group", "unknown"}:
                if candidate.type == "code":
                    break
                continue
            if not (candidate.text or "").strip():
                continue
            if not _is_known_callout_body_candidate(
                candidate,
                main_left,
                main_right,
                indent_threshold,
            ):
                break
            if not _is_same_callout_cluster(previous, candidate):
                break
            group.append(candidate)
            previous = candidate
            if len(group) >= 8:
                break

        if len(group) < 2:
            continue

        anchor_count += 1
        _apply_callout_group(
            title,
            group,
            callout_id=f"callout-p{title.page_number}-anchor{anchor_count}",
        )


def _apply_callout_group(
    title: ManifestElement,
    group: list[ManifestElement],
    *,
    callout_id: str,
) -> None:
    if title.type == "heading":
        original_type = title.type
        title.type = "paragraph"
        title.metadata["original_type"] = original_type
        title.metadata["demoted_from_heading"] = True
    title.metadata["is_callout_title"] = True
    title.metadata["callout_id"] = callout_id
    title.metadata["callout_role"] = "title"
    title.metadata["callout_type"] = "note"
    title.metadata["callout_title"] = title.text or ""

    for item in group[1:]:
        item.metadata["callout_id"] = callout_id
        item.metadata["callout_role"] = "content"
        item.metadata.setdefault("callout_type", "note")
        item.metadata.setdefault("callout_title", title.text or "")


def _estimate_main_text_band(elements: list[ManifestElement]) -> tuple[float, float]:
    wide = []
    all_boxes = []
    for element in elements:
        bbox = _element_bbox(element)
        if bbox is None:
            continue
        left, _, right, _ = bbox
        width = right - left
        all_boxes.append((left, right, width))

    if not all_boxes:
        return (0.0, 0.0)

    max_width = max(width for _, _, width in all_boxes)
    for left, right, width in all_boxes:
        if width >= max_width * 0.75:
            wide.append((left, right))

    reference = wide or [(left, right) for left, right, _ in all_boxes]
    main_left = min(left for left, _ in reference)
    main_right = max(right for _, right in reference)
    return (main_left, main_right)


def _is_same_callout_cluster(previous: ManifestElement, current: ManifestElement) -> bool:
    prev_bbox = _element_bbox(previous)
    curr_bbox = _element_bbox(current)
    if prev_bbox is None or curr_bbox is None:
        return False

    _, prev_top, _, prev_bottom = prev_bbox
    _, curr_top, _, _ = curr_bbox
    vertical_gap = curr_top - prev_bottom
    if vertical_gap > CALL_OUT_MAX_VERTICAL_GAP:
        return False

    prev_left, _, prev_right, _ = prev_bbox
    curr_left, _, curr_right, _ = curr_bbox
    overlap_left = max(prev_left, curr_left)
    overlap_right = min(prev_right, curr_right)
    overlap_width = max(0.0, overlap_right - overlap_left)
    min_width = max(1.0, min(prev_right - prev_left, curr_right - curr_left))
    return (overlap_width / min_width) >= 0.55


def _element_bbox(element: ManifestElement) -> tuple[float, float, float, float] | None:
    if not element.provenance:
        return None
    bbox = element.provenance[0].bbox
    if bbox is None:
        return None
    return (bbox.left, bbox.top, bbox.right, bbox.bottom)


def _is_callout_title_candidate(element: ManifestElement) -> bool:
    if element.type == "heading":
        return True
    if element.type != "paragraph":
        return False
    text = (element.text or "").strip()
    if not text:
        return False
    if _is_known_callout_title(text):
        return True
    if len(text) > 95:
        return False
    upper_ratio = _uppercase_ratio(text)
    if upper_ratio >= 0.55:
        return True
    return text.endswith(("?", ":"))


def _uppercase_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    uppers = [ch for ch in letters if ch.isupper()]
    return len(uppers) / len(letters)


def _normalize_text_key(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return normalized


def _is_known_callout_title(text: str) -> bool:
    return _normalize_text_key(text) in KNOWN_CALLOUT_TITLES


def _is_known_callout_body_candidate(
    element: ManifestElement,
    main_left: float,
    main_right: float,
    indent_threshold: float,
) -> bool:
    bbox = _element_bbox(element)
    if bbox is None:
        return False
    left, _, right, bottom = bbox
    width = right - left
    band_width = max(1.0, main_right - main_left)
    left_indent = left - main_left
    right_indent = main_right - right
    if bottom <= 0:
        return False
    if width > band_width * 0.98:
        return False
    if right_indent < 4.0:
        return False
    return (left_indent >= indent_threshold) or (right_indent >= indent_threshold)


def _refine_reading_order(elements: list[ManifestElement]) -> list[ManifestElement]:
    """Refine reading order with column-aware gutter partitioning and marginals isolation.

    Ensures headers stay at the top, footers/page numbers stay at the base (never
    interleaved inside paragraphs), and body blocks follow a clean multi-column
    reading order (reading column 1 before column 2/3).
    """
    if not elements:
        return elements

    by_page: dict[int | None, list[ManifestElement]] = {}
    for elem in elements:
        by_page.setdefault(elem.page_number, []).append(elem)

    refined: list[ManifestElement] = []
    for page_no, page_elements in sorted(
        by_page.items(),
        key=lambda pair: (0 if pair[0] is None else 1, pair[0] or 0),
    ):
        if page_no is None or len(page_elements) <= 1:
            refined.extend(page_elements)
            continue

        groups: list[ManifestElement] = []
        headers: list[ManifestElement] = []
        footers: list[ManifestElement] = []
        body: list[ManifestElement] = []

        for e in page_elements:
            etype = str(e.type).lower()
            raw = str(e.raw_label).lower()
            is_header = etype in ("header", "page_header") or raw in ("header", "page_header")
            is_footer = (
                etype in ("footer", "page_footer", "page_number")
                or raw in ("footer", "page_footer", "page_number")
            )
            if etype == "group":
                groups.append(e)
            elif is_header:
                headers.append(e)
            elif is_footer:
                footers.append(e)
            else:
                body.append(e)

        # Sort headers top-to-bottom, left-to-right
        headers.sort(
            key=lambda item: (
                _element_bbox(item)[1] if _element_bbox(item) else 0.0,
                _element_bbox(item)[0] if _element_bbox(item) else 0.0,
                item.reading_order,
            )
        )

        # Sort footers top-to-bottom, left-to-right
        footers.sort(
            key=lambda item: (
                _element_bbox(item)[1] if _element_bbox(item) else 0.0,
                _element_bbox(item)[0] if _element_bbox(item) else 0.0,
                item.reading_order,
            )
        )

        sorted_body = _order_body_elements_by_column(body)
        refined.extend(groups + headers + sorted_body + footers)

    for index, elem in enumerate(refined, start=1):
        elem.reading_order = index

    return refined


def _order_body_elements_by_column(body: list[ManifestElement]) -> list[ManifestElement]:
    """Order body elements respecting multi-column gutters and full-width banners."""
    elements_with_bbox = [e for e in body if _element_bbox(e) is not None]
    if len(elements_with_bbox) < 2:
        return sorted(
            body,
            key=lambda e: (
                _element_bbox(e)[1] if _element_bbox(e) else 0.0,
                e.reading_order,
            ),
        )

    min_left = min(_element_bbox(e)[0] for e in elements_with_bbox)
    max_right = max(_element_bbox(e)[2] for e in elements_with_bbox)
    page_width = max(1.0, max_right - min_left)

    # Detect multi-column candidates (width < 75% of content width)
    narrow_elements = [
        e
        for e in elements_with_bbox
        if (_element_bbox(e)[2] - _element_bbox(e)[0]) < (0.75 * page_width)
    ]

    mid_x = min_left + 0.5 * page_width
    col1 = [
        e
        for e in narrow_elements
        if _element_bbox(e)[2] <= (mid_x + 0.05 * page_width)
    ]
    col2 = [
        e
        for e in narrow_elements
        if _element_bbox(e)[0] >= (mid_x - 0.05 * page_width)
    ]

    is_multi_column = len(col1) >= 2 and len(col2) >= 2

    if not is_multi_column:
        return sorted(
            body,
            key=lambda e: (
                _element_bbox(e)[1] if _element_bbox(e) else 0.0,
                _element_bbox(e)[0] if _element_bbox(e) else 0.0,
                e.reading_order,
            ),
        )

    full_width = [
        e
        for e in elements_with_bbox
        if (_element_bbox(e)[2] - _element_bbox(e)[0]) >= (0.75 * page_width)
    ]
    full_width.sort(key=lambda e: _element_bbox(e)[1])

    ordered: list[ManifestElement] = []
    seen_ids: set[str] = set()
    prev_top = -1.0

    for fw in full_width:
        fw_top = _element_bbox(fw)[1]
        segment = [
            e
            for e in narrow_elements
            if prev_top < _element_bbox(e)[1] < fw_top and e.id not in seen_ids
        ]
        seg_c1 = [
            e
            for e in segment
            if (_element_bbox(e)[0] + _element_bbox(e)[2]) / 2.0 < mid_x
        ]
        seg_c2 = [
            e
            for e in segment
            if (_element_bbox(e)[0] + _element_bbox(e)[2]) / 2.0 >= mid_x
        ]
        seg_c1.sort(key=lambda e: (_element_bbox(e)[1], _element_bbox(e)[0]))
        seg_c2.sort(key=lambda e: (_element_bbox(e)[1], _element_bbox(e)[0]))
        for el in seg_c1:
            ordered.append(el)
            seen_ids.add(el.id)
        for el in seg_c2:
            ordered.append(el)
            seen_ids.add(el.id)
        ordered.append(fw)
        seen_ids.add(fw.id)
        prev_top = _element_bbox(fw)[3]

    remainder = [
        e
        for e in narrow_elements
        if _element_bbox(e)[1] > prev_top and e.id not in seen_ids
    ]
    rem_c1 = [
        e
        for e in remainder
        if (_element_bbox(e)[0] + _element_bbox(e)[2]) / 2.0 < mid_x
    ]
    rem_c2 = [
        e
        for e in remainder
        if (_element_bbox(e)[0] + _element_bbox(e)[2]) / 2.0 >= mid_x
    ]
    rem_c1.sort(key=lambda e: (_element_bbox(e)[1], _element_bbox(e)[0]))
    rem_c2.sort(key=lambda e: (_element_bbox(e)[1], _element_bbox(e)[0]))
    for el in rem_c1:
        ordered.append(el)
        seen_ids.add(el.id)
    for el in rem_c2:
        ordered.append(el)
        seen_ids.add(el.id)

    for e in body:
        if e.id not in seen_ids:
            ordered.append(e)
            seen_ids.add(e.id)

    return ordered


def _build_pages(document: Any, elements: list[ManifestElement]) -> list[PageDescriptor]:
    by_page: dict[int, list[str]] = {}
    for element in elements:
        if element.page_number is not None:
            by_page.setdefault(element.page_number, []).append(element.id)

    pages: list[PageDescriptor] = []
    raw_pages = getattr(document, "pages", {}) or {}
    for page_number, page in sorted(raw_pages.items(), key=lambda pair: int(pair[0])):
        number = int(page_number)
        size = getattr(page, "size", None)
        pages.append(
            PageDescriptor(
                page_number=number,
                width=_optional_float(getattr(size, "width", None)),
                height=_optional_float(getattr(size, "height", None)),
                element_ids=by_page.get(number, []),
            )
        )

    if not pages:
        page_count = _page_count(document)
        for number in range(1, page_count + 1):
            pages.append(
                PageDescriptor(
                    page_number=number,
                    element_ids=by_page.get(number, []),
                )
            )
    return pages


def _derive_processing_needs(
    elements: list[ManifestElement],
) -> tuple[list[Observation], list[Obligation]]:
    observations: list[Observation] = []
    obligations: list[Obligation] = []

    for element in elements:
        spec = OBLIGATION_BY_TYPE.get(element.type)
        if spec is None:
            continue
        kind, rationale, methods = spec
        suffix = element.id.removeprefix("element-")
        observations.append(
            Observation(
                id=f"observation-{kind}-{suffix}",
                kind=f"{element.type}-requires-processing",
                severity="warning" if element.type != "code" else "info",
                message=rationale,
                target_ids=[element.id],
                evidence={
                    "raw_label": element.raw_label,
                    "page_number": element.page_number,
                },
            )
        )
        obligations.append(
            Obligation(
                id=f"obligation-{kind}-{suffix}",
                kind=kind,
                target_ids=[element.id],
                admissible_methods=methods,
                method_costs={
                    method: DEFAULT_METHOD_COSTS.get(method, 50)
                    for method in methods
                },
                rationale=rationale,
            )
        )

    heading_levels = [
        (element.id, element.hierarchy_level)
        for element in elements
        if element.type == "heading"
    ]
    previous = 0
    for element_id, level in heading_levels:
        if previous and level > previous + 1:
            suffix = element_id.removeprefix("element-")
            message = t(MSG_HEADING_GAP).format(previous=previous, level=level)
            observations.append(
                Observation(
                    id=f"observation-heading-gap-{suffix}",
                    kind="heading-hierarchy-gap",
                    severity="error",
                    message=message,
                    target_ids=[element_id],
                    evidence={"previous_level": previous, "current_level": level},
                )
            )
            obligations.append(
                Obligation(
                    id=f"obligation-repair-heading-{suffix}",
                    kind="repair-heading-hierarchy",
                    target_ids=[element_id],
                    admissible_methods=["deterministic-heading-repair", "human-review"],
                    method_costs={
                        "deterministic-heading-repair": DEFAULT_METHOD_COSTS[
                            "deterministic-heading-repair"
                        ],
                        "human-review": DEFAULT_METHOD_COSTS["human-review"],
                    },
                    rationale=message,
                )
            )
        previous = level
    return observations, obligations


def _derive_v23_processing_needs(
    elements: list[ManifestElement],
    *,
    page_sizes: dict[int, tuple[float | None, float | None]] | None = None,
    fusion_evidence: Any = None,
    fusion_stats: Any = None,
) -> tuple[list[Observation], list[Obligation]]:
    """Emit v2.3 needs only when deterministic checks or fusion evidence support them."""
    from docstruct.fusion.line_numbers import extract_line_numbers
    from docstruct.fusion.tailjoin import join_tail, page_number_position, tailjoin3
    from docstruct.fusion.types import DiffBlock
    from docstruct.fusion.verse import verse_blocks
    from docstruct.fusion.xycut import xycut_order
    from docstruct.text.latex import normalize_latex
    from docstruct.text.norm_fix import norm_fix

    candidates: list[tuple[str, list[ManifestElement], dict[str, Any]]] = []
    by_page: dict[int | None, list[ManifestElement]] = {}
    for element in elements:
        by_page.setdefault(element.page_number, []).append(element)

    def add(
        kind: str,
        targets: list[ManifestElement],
        evidence: dict[str, Any],
    ) -> None:
        valid_targets = [item for item in targets if item.id]
        if valid_targets:
            candidates.append((kind, valid_targets, evidence))

    for element in elements:
        text = element.text or ""
        if element.type == "formula" and text:
            normalized = normalize_latex(text)
            if normalized != text:
                add("normalize-formula", [element], {"before": text, "after": normalized})
        elif element.type in {"paragraph", "heading", "title", "list_item", "caption"} and text:
            normalized = norm_fix(text)
            if normalized != text:
                add("normalize-text", [element], {"before": text, "after": normalized})

    for page_number, page_elements in by_page.items():
        positioned = [
            item for item in page_elements
            if _normalized_element_bbox(item, page_sizes) is not None
        ]
        if len(positioned) > 1:
            current = sorted(positioned, key=lambda item: item.reading_order)
            boxes = [_normalized_element_bbox(item, page_sizes) for item in current]
            order = xycut_order([box for box in boxes if box is not None])
            if order != list(range(len(current))):
                reordered_ids = [current[index].id for index in order]
                add(
                    "refine-reading-order",
                    current,
                    {
                        "page_number": page_number,
                        "order_before": [item.id for item in current],
                        "order_after": reordered_ids,
                    },
                )

        text_elements = [
            item for item in page_elements
            if item.text and item.type not in {"formula", "table", "picture"}
        ]
        if not text_elements:
            continue
        blocks = [
            DiffBlock(
                md=item.text or "",
                kind="text",
                box=_normalized_element_bbox(item, page_sizes),
                text=item.text or "",
                type=item.type,
                role=(
                    "header" if item.type == "page_header"
                    else "footer" if item.type == "page_footer"
                    else "page_number" if item.type == "page_number"
                    else None
                ),
            )
            for item in text_elements
        ]

        verse_stats: Counter = Counter()
        verse_blocks(blocks, verse_stats, "manifest", 300, "records")
        if verse_stats.get("verse-manifest-split", 0):
            add(
                "chunk-verse",
                text_elements,
                {"chunks": verse_stats["verse-manifest-chunks"]},
            )

        line_stats: Counter = Counter()
        extract_line_numbers(blocks, line_stats, "manifest")
        if line_stats.get("line-numbers-manifest-count", 0):
            add(
                "extract-line-numbers",
                text_elements,
                {"count": line_stats["line-numbers-manifest-count"]},
            )

        page_text = [item.text or "" for item in text_elements]
        position = page_number_position(blocks)
        if position is not None:
            joined = tailjoin3(page_text, position, 50, 3, "keep")
        else:
            joined = join_tail(page_text, "end", 50, 3)
        if joined != page_text:
            tail_targets = text_elements[len(text_elements) - (len(page_text) - len(joined) + 1):]
            add(
                "join-tail-blocks",
                tail_targets,
                {"position": position, "before_count": len(page_text), "after_count": len(joined)},
            )

    stats = fusion_stats
    if not isinstance(stats, dict) and isinstance(fusion_evidence, dict):
        stats = fusion_evidence.get("stats")
    if isinstance(fusion_evidence, dict):
        pages = fusion_evidence.get("pages")
        if isinstance(pages, list):
            for page_data in pages:
                if not isinstance(page_data, dict):
                    continue
                page_stats = page_data.get("stats")
                page_number = page_data.get("page_number")
                page_targets = by_page.get(page_number, [])
                if not isinstance(page_stats, dict) or not page_targets:
                    continue
                _add_fusion_observations(add, page_targets, page_stats, page_number)
    elif isinstance(stats, dict):
        targets = [element for element in elements if element.text]
        if targets:
            _add_fusion_observations(add, targets, stats, None)

    observations: list[Observation] = []
    obligations: list[Obligation] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for kind, targets, evidence in candidates:
        target_ids = list(dict.fromkeys(item.id for item in targets))
        key = (kind, tuple(target_ids))
        if key in seen:
            continue
        seen.add(key)
        rationale, methods = V23_OBLIGATION_BY_KIND[kind]
        suffix = "-".join(item.removeprefix("element-") for item in target_ids)
        observations.append(
            Observation(
                id=f"observation-{kind}-{suffix}",
                kind=f"{kind}-detected",
                severity="warning",
                message=rationale,
                target_ids=target_ids,
                evidence=evidence,
            )
        )
        obligations.append(
            Obligation(
                id=f"obligation-{kind}-{suffix}",
                kind=kind,
                target_ids=target_ids,
                admissible_methods=methods,
                method_costs={
                    method: DEFAULT_METHOD_COSTS.get(method, 50)
                    for method in methods
                },
                rationale=rationale,
            )
        )
    return observations, obligations


def _add_fusion_observations(
    add: Any,
    targets: list[ManifestElement],
    stats: dict[str, Any],
    page_number: int | None,
) -> None:
    if not stats:
        return
    if stats.get("text_divergence"):
        add("adjudicate-page", targets, {"page_number": page_number, "fusion_stats": stats})
    if stats.get("provider_divergence"):
        add("fuse-providers", targets, {"page_number": page_number, "fusion_stats": stats})
    if any(key.startswith("dropped-") and value for key, value in stats.items()):
        add("rescue-omitted-block", targets, {"page_number": page_number, "fusion_stats": stats})
    if stats.get("table_divergence"):
        table_targets = [item for item in targets if item.type == "table"]
        if table_targets:
            add(
                "select-table-source",
                table_targets,
                {"page_number": page_number, "fusion_stats": stats},
            )
    cut_count = stats.get("repetition_tokens_cut", 0)
    if cut_count:
        add(
            "guard-repetition",
            targets,
            {"page_number": page_number, "tokens_cut": cut_count},
        )


def _normalized_element_bbox(
        element: ManifestElement,
        page_sizes: dict[int, tuple[float | None, float | None]] | None,
) -> tuple[float, float, float, float] | None:
        bbox = _element_bbox(element)
        if bbox is None or element.page_number is None or page_sizes is None:
            return None
        size = page_sizes.get(element.page_number)
        if size is None:
            return None
        width, height = size
        if not width or not height:
            return None
        left, top, right, bottom = bbox
        provenance_bbox = next(
            (item.bbox for item in element.provenance if item.bbox is not None),
            None,
        )
        if provenance_bbox and provenance_bbox.coord_origin == "BOTTOMLEFT":
            top, bottom = height - top, height - bottom
        return (
            left / width,
            top / height,
            right / width,
            bottom / height,
        )


def _append_processing_needs(
    manifest: ProcessingManifest,
    observations: list[Observation],
    obligations: list[Obligation],
) -> None:
    existing_observations = {item.id for item in manifest.observations}
    existing_obligations = {item.id for item in manifest.obligations}
    existing_pairs = {
        (item.kind, tuple(item.target_ids)) for item in manifest.obligations
    }
    manifest.observations.extend(
        item for item in observations if item.id not in existing_observations
    )
    for item in obligations:
        pair = (item.kind, tuple(item.target_ids))
        if item.id not in existing_obligations and pair not in existing_pairs:
            manifest.obligations.append(item)
            existing_pairs.add(pair)
    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)


def reconcile_reclassified_element_processing_needs(
    manifest: ProcessingManifest,
    element: ManifestElement,
    *,
    previous_type: str,
) -> None:
    """Reconcile derived observations/obligations after an element changes type.

    Only the standard processing need associated with the reclassified element
    is replaced; every other observation/obligation (e.g. the v2.3 needs
    derived from dual-provider fusion evidence) is kept untouched instead of
    rebuilding the complete list.
    """
    if previous_type == element.type:
        return

    previous_spec = OBLIGATION_BY_TYPE.get(previous_type)
    current_spec = OBLIGATION_BY_TYPE.get(element.type)
    if current_spec is None:
        return

    current_kind, rationale, methods = current_spec
    previous_kind = previous_spec[0] if previous_spec is not None else None
    previous_observation_kind = (
        f"{previous_type}-requires-processing" if previous_spec is not None else None
    )
    current_observation_kind = f"{element.type}-requires-processing"
    suffix = element.id.removeprefix("element-")
    current_obligation_id = f"obligation-{current_kind}-{suffix}"
    current_observation_id = f"observation-{current_kind}-{suffix}"

    removed_obligation_ids: set[str] = set()
    retained_obligations: list[Obligation] = []
    has_current_obligation = False
    for obligation in manifest.obligations:
        targets_only_element = obligation.target_ids == [element.id]
        if targets_only_element and obligation.kind == current_kind:
            has_current_obligation = True
        if (
            targets_only_element
            and previous_kind is not None
            and obligation.kind == previous_kind
        ):
            removed_obligation_ids.add(obligation.id)
            continue
        retained_obligations.append(obligation)

    if not has_current_obligation:
        retained_obligations.append(
            Obligation(
                id=current_obligation_id,
                kind=current_kind,
                target_ids=[element.id],
                admissible_methods=list(methods),
                method_costs={
                    method: DEFAULT_METHOD_COSTS.get(method, 50)
                    for method in methods
                },
                rationale=rationale,
            )
        )

    replacement_id = next(
        (
            obligation.id
            for obligation in retained_obligations
            if obligation.target_ids == [element.id]
            and obligation.kind == current_kind
        ),
        current_obligation_id,
    )
    for obligation in retained_obligations:
        obligation.dependencies = [
            replacement_id if dependency in removed_obligation_ids else dependency
            for dependency in obligation.dependencies
        ]
    manifest.obligations = retained_obligations

    retained_observations: list[Observation] = []
    has_current_observation = False
    for observation in manifest.observations:
        targets_only_element = observation.target_ids == [element.id]
        if targets_only_element and observation.kind == current_observation_kind:
            has_current_observation = True
        if (
            targets_only_element
            and previous_observation_kind is not None
            and observation.kind == previous_observation_kind
        ):
            continue
        retained_observations.append(observation)

    if not has_current_observation:
        retained_observations.append(
            Observation(
                id=current_observation_id,
                kind=current_observation_kind,
                severity="warning" if element.type != "code" else "info",
                message=rationale,
                target_ids=[element.id],
                evidence={
                    "raw_label": element.raw_label,
                    "page_number": element.page_number,
                },
            )
        )
    manifest.observations = retained_observations

    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)
    manifest.summary.element_types = dict(
        sorted(Counter(item.type for item in manifest.elements).items())
    )


def _item_label(item: Any) -> str:
    label = getattr(item, "label", None)
    if label is None:
        label = getattr(item, "name", None)
    value = getattr(label, "value", label)
    text = str(value or item.__class__.__name__).strip().lower()
    text = text.removeprefix("docitemlabel.").removeprefix("grouplabel.")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "unknown"


def _fallback_type(item: Any, raw_label: str) -> str:
    class_name = item.__class__.__name__.lower()
    if "group" in class_name or raw_label in {
        "list",
        "ordered_list",
        "chapter",
        "section",
        "sheet",
        "body",
        "unspecified",
    }:
        return "group"
    return "unknown"


def _item_text(item: Any, element_type: str) -> str | None:
    for attribute in ("text", "orig", "name"):
        value = getattr(item, attribute, None)
        if isinstance(value, str) and value.strip():
            if element_type == "code":
                return value.replace("\r\n", "\n").replace("\r", "\n")
            cleaned = sanitize_text(value)
            return cleaned or None
    return None


def _hierarchy_level(item: Any, element_type: str, tree_level: int) -> int:
    if element_type == "title":
        return 1
    if element_type == "heading":
        explicit = getattr(item, "level", None)
        if isinstance(explicit, int) and explicit >= 1:
            return explicit
        return max(1, int(tree_level))
    return max(0, int(tree_level))


def _provenance(item: Any) -> list[Provenance]:
    records: list[Provenance] = []
    for raw in getattr(item, "prov", None) or []:
        page_number = getattr(raw, "page_no", None)
        if not isinstance(page_number, int) or page_number < 1:
            continue
        bbox = _bbox(getattr(raw, "bbox", None))
        charspan = getattr(raw, "charspan", None)
        char_start = char_end = None
        if isinstance(charspan, (tuple, list)) and len(charspan) == 2:
            char_start, char_end = int(charspan[0]), int(charspan[1])
        records.append(
            Provenance(
                page_number=page_number,
                bbox=bbox,
                char_start=char_start,
                char_end=char_end,
            )
        )
    return records


def _bbox(raw: Any) -> BoundingBox | None:
    if raw is None:
        return None
    try:
        origin = getattr(getattr(raw, "coord_origin", None), "value", None)
        origin_text = str(origin or "UNKNOWN").upper()
        if origin_text not in {"TOPLEFT", "BOTTOMLEFT"}:
            origin_text = "UNKNOWN"
        return BoundingBox(
            left=float(getattr(raw, "l")),
            top=float(getattr(raw, "t")),
            right=float(getattr(raw, "r")),
            bottom=float(getattr(raw, "b")),
            coord_origin=origin_text,
        )
    except (AttributeError, TypeError, ValueError):
        return None


def _reference(raw: Any) -> str | None:
    if raw is None:
        return None
    value = getattr(raw, "cref", raw)
    if isinstance(value, dict):
        value = value.get("$ref") or value.get("cref")
    text = str(value).strip()
    return text or None


def _confidence(item: Any) -> float | None:
    for attribute in ("confidence", "score"):
        value = getattr(item, attribute, None)
        if isinstance(value, (int, float)) and 0 <= float(value) <= 1:
            return float(value)
    return None


def _safe_metadata(item: Any, *, element_type: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"docling_class": item.__class__.__name__}
    content_layer = getattr(item, "content_layer", None)
    if content_layer is not None:
        metadata["content_layer"] = str(getattr(content_layer, "value", content_layer))
    enumerated = getattr(item, "enumerated", None)
    if isinstance(enumerated, bool):
        metadata["enumerated"] = enumerated
    marker = getattr(item, "marker", None)
    if isinstance(marker, str) and marker:
        metadata["marker"] = marker

    if element_type == "table":
        table_ast = _extract_table_ast(item)
        if table_ast is not None:
            metadata["table_ast"] = table_ast
            rows = rows_from_table_ast(table_ast)
            if rows:
                metadata["table_row_count"] = len(rows)
                metadata["table_column_count"] = max((len(row) for row in rows), default=0)
            metadata["table_has_header"] = bool(table_ast.get("header"))
            metadata["table_linearization_hint"] = "docling-structured"
    return metadata


def _extract_table_ast(item: Any) -> dict[str, Any] | None:
    raw_candidates: list[Any] = []
    for attr_name in (
        "table_ast",
        "table",
        "table_data",
        "grid",
        "rows",
        "cells",
    ):
        value = getattr(item, attr_name, None)
        if value is not None:
            raw_candidates.append(value)

    for method_name in ("model_dump", "to_dict", "export_to_dict"):
        method = getattr(item, method_name, None)
        if not callable(method):
            continue
        try:
            payload = method()
        except TypeError:
            try:
                payload = method(mode="json")
            except Exception:
                continue
        except Exception:
            continue
        if isinstance(payload, dict):
            raw_candidates.append(payload)
            for nested_key in (
                "table_ast",
                "table",
                "table_data",
                "grid",
                "rows",
                "cells",
            ):
                nested = payload.get(nested_key)
                if nested is not None:
                    raw_candidates.append(nested)

    for candidate in raw_candidates:
        table_ast = normalize_table_ast(candidate)
        if table_ast is not None:
            return table_ast
    return None


def _infer_title(source_path: Path, elements: list[ManifestElement]) -> str:
    titles = [
        (element.text or "").strip()
        for element in elements
        if element.type == "title" and (element.text or "").strip()
    ]
    if titles:
        return titles[0]

    headings = [
        (element.text or "").strip()
        for element in elements
        if element.type == "heading" and (element.text or "").strip()
    ]
    if len(headings) >= 2 and _looks_like_chapter_heading(headings[0]):
        return f"{headings[0]} - {headings[1]}"
    if headings:
        return headings[0]
    return source_path.stem


def _looks_like_chapter_heading(text: str) -> bool:
    normalized = text.strip().upper()
    return bool(re.match(r"^CAP[ÍI]TULO\s+\d+", normalized))


def _page_count(document: Any) -> int:
    num_pages = getattr(document, "num_pages", None)
    if callable(num_pages):
        try:
            return max(0, int(num_pages()))
        except (TypeError, ValueError):
            pass
    return 0


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
