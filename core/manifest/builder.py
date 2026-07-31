from __future__ import annotations

import hashlib
import mimetypes
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.sanitizer import sanitize_text

from core.manifest.docling_extractor import DoclingExtraction
from core.manifest.models import (
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
        "A imagem deve receber descrição ou ser marcada como decorativa.",
        ["vision-description", "human-review"],
    ),
    "table": (
        "linearize-table",
        "A tabela deve ter cabeçalhos e ordem de leitura verificáveis.",
        ["docling-table", "pandoc-table", "human-review"],
    ),
    "formula": (
        "verbalize-formula",
        "A fórmula deve possuir representação matemática acessível e verbalização.",
        ["mathml", "latex-verbalizer", "human-review"],
    ),
    "code": (
        "preserve-code-semantics",
        "O bloco de código deve preservar indentação, linguagem e leitura literal.",
        ["pandoc-code", "human-review"],
    ),
    "unknown": (
        "review-structure",
        "O elemento não classificado requer inspeção estrutural.",
        ["docling-retry", "pymupdf-region", "human-review"],
    ),
}

DEFAULT_METHOD_COSTS = {
    "vision-description": 20,
    "docling-table": 10,
    "pandoc-table": 15,
    "mathml": 10,
    "latex-verbalizer": 20,
    "pandoc-code": 10,
    "docling-retry": 25,
    "pymupdf-region": 30,
    "deterministic-heading-repair": 5,
    "human-review": 100,
}


def build_processing_manifest(
    source_path: Path,
    extraction: DoclingExtraction,
    *,
    language: str = "pt-BR",
) -> ProcessingManifest:
    source_path = source_path.resolve()
    digest = _sha256(source_path)
    elements = _build_elements(extraction.document)
    pages = _build_pages(extraction.document, elements)
    title = _infer_title(source_path, elements)
    observations, obligations = _derive_processing_needs(elements)
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


def _build_elements(document: Any) -> list[ManifestElement]:
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
        metadata = _safe_metadata(item)
        elements.append(
            ManifestElement(
                id=f"element-{reading_order:06d}",
                type=element_type,
                raw_label=raw_label,
                reading_order=reading_order,
                hierarchy_level=hierarchy_level,
                text=_item_text(item),
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
    return elements


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
            message = (
                f"A hierarquia de títulos salta do nível {previous} para o nível "
                f"{level}."
            )
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


def _item_text(item: Any) -> str | None:
    for attribute in ("text", "orig", "name"):
        value = getattr(item, attribute, None)
        if isinstance(value, str) and value.strip():
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


def _safe_metadata(item: Any) -> dict[str, Any]:
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
    return metadata


def _infer_title(source_path: Path, elements: list[ManifestElement]) -> str:
    for element in elements:
        if element.type == "title" and element.text:
            return element.text
    for element in elements:
        if element.type == "heading" and element.text:
            return element.text
    return source_path.stem


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
