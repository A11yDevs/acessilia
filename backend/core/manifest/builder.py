from __future__ import annotations

import hashlib
import mimetypes
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.i18n import t
from backend.log_messages import (
    MSG_HEADING_GAP,
    MSG_OBLIGATION_CODE,
    MSG_OBLIGATION_FORMULA,
    MSG_OBLIGATION_IMAGE,
    MSG_OBLIGATION_TABLE,
    MSG_OBLIGATION_UNKNOWN,
    MSG_OBLIGATION_UNSTRUCTURED_PAGE,
    MSG_OBSERVATION_PAGE_WITHOUT_STRUCTURE,
)

from backend.core.manifest.models import (
    Artifact,
    BoundingBox,
    ManifestElement,
    Obligation,
    Observation,
    ProcessingManifest,
    is_bottom_left,
)

if TYPE_CHECKING:
    from backend.core.manifest.toolbox_extractor import ToolboxExtraction


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
    "vision-page-inspection": 25,
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
    "inspect-unstructured-page": (
        "Página sem estrutura extraída exige inspeção visual.",
        ["vision-page-inspection", "human-review"],
    ),
}

#: Artifact holding the secondary provider's extraction when FUSION_MODE=dual;
#: the v2.3 methods that choose between providers read it.
#: A page the extractor returned without any element gets a placeholder element
#: of this raw label, an observation and a critical obligation: the page is
#: inspected visually and either described or accepted as blank.
UNSTRUCTURED_PAGE_LABEL = "unstructured-page"
UNSTRUCTURED_PAGE_OBSERVATION_KIND = "page-without-structure"
UNSTRUCTURED_PAGE_OBLIGATION_KIND = "inspect-unstructured-page"
UNSTRUCTURED_PAGE_METHODS = V23_OBLIGATION_BY_KIND[UNSTRUCTURED_PAGE_OBLIGATION_KIND][1]

SECONDARY_EXTRACTION_KIND = "provider-extraction"
SECONDARY_EXTRACTION_ARTIFACT_ID = "artifact-secondary-extraction"


def build_processing_manifest(
    source_path: Path,
    extraction: ToolboxExtraction,
    *,
    language: str = "pt-BR",
    refine_reading_order: bool = False,
) -> ProcessingManifest:
    """Builds the processing manifest from the Toolbox structural extraction.

    The Toolbox is the only extractor (docs/adr/0003): ``extraction.document``
    is its JSON response, whose elements already carry callouts, code text and
    table structure. This core adds its own planning policy on top.

    Raises:
        TypeError: When the extraction is not a Toolbox JSON response.
    """
    document = getattr(extraction, "document", None)
    if not isinstance(document, dict):
        raise TypeError(
            "build_processing_manifest expects the Toolbox JSON extraction, "
            f"got {type(document).__name__}"
        )
    source_path = source_path.resolve()
    return _build_from_toolbox_json(
        source_path,
        extraction,
        digest=_sha256(source_path),
        language=language,
        refine_reading_order=refine_reading_order,
    )


def _build_from_toolbox_json(
    source_path: Path,
    extraction: ToolboxExtraction,
    *,
    digest: str,
    language: str,
    refine_reading_order: bool = False,
) -> ProcessingManifest:
    """Build a ProcessingManifest from a pre-built Toolbox JSON response.

    The Toolbox already returns a complete ProcessingManifest-compatible JSON
    payload inside ``extraction.document["document"]``, so we parse it directly.
    """
    data: dict[str, Any] = dict(extraction.document["document"])

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
        "name": data.get("extractor", {}).get(
            "name", extraction.configuration.get("toolbox_provider") or "toolbox"
        ),
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
    # methods the core does not implement) are discarded and derived below.
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
    append_unstructured_page_needs(manifest)
    secondary = extraction.document.get("secondary_extraction")
    if isinstance(secondary, dict) and secondary.get("path"):
        manifest.artifacts.append(
            Artifact(
                id=SECONDARY_EXTRACTION_ARTIFACT_ID,
                kind=SECONDARY_EXTRACTION_KIND,
                path=str(secondary["path"]),
                media_type="application/json",
                sha256=secondary.get("sha256"),
            )
        )
    return manifest


def _raw_bbox(element: ManifestElement) -> BoundingBox | None:
    if not element.provenance:
        return None
    return element.provenance[0].bbox


def _element_bbox(element: ManifestElement) -> tuple[float, float, float, float] | None:
    """Element box with the y axis growing downwards, whatever the source origin.

    Reading-order refinement compares ``top`` and ``bottom`` as screen
    coordinates. A bottom-left box is mirrored (``y -> -y``): that keeps every
    comparison right without knowing the page height.

    Only differences and orderings are meaningful: a mirrored ``top`` or
    ``bottom`` is negative, so never compare it with a fixed position such as
    ``0``. ``_normalized_element_bbox`` gives page fractions instead.
    """
    bbox = _raw_bbox(element)
    if bbox is None:
        return None
    if is_bottom_left(bbox.coord_origin, bbox.top, bbox.bottom):
        return (bbox.left, -bbox.top, bbox.right, -bbox.bottom)
    return (bbox.left, bbox.top, bbox.right, bbox.bottom)


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


def is_unstructured_page_placeholder(element: ManifestElement) -> bool:
    """Whether ``element`` stands for a page the extractor left without structure."""
    return element.raw_label == UNSTRUCTURED_PAGE_LABEL and bool(
        element.metadata.get("unstructured_page")
    )


def append_unstructured_page_needs(manifest: ProcessingManifest) -> None:
    """Give every page without elements a placeholder and a visual-inspection obligation.

    An extractor can return a page with no element when it is blank, or when its
    content is purely visual (a scan, a photo, a diagram). Telling them apart
    needs a look at the page, so the page becomes an explicit planning need:
    the critical ``inspect-unstructured-page`` obligation, satisfied by
    describing the page or by accepting it as blank. Without it, the content of
    such a page would be lost silently.
    """
    known = {element.id for element in manifest.elements}
    # Same rule as the payload builder: a page without element_ids still has
    # structure when elements point at it by page_number.
    numbered = {element.page_number or 1 for element in manifest.elements}
    next_order = max((element.reading_order for element in manifest.elements), default=0)
    for page in sorted(manifest.pages, key=lambda item: item.page_number):
        if page.element_ids or page.page_number in numbered:
            continue
        number = page.page_number
        element_id = f"element-unstructured-page-{number:04d}"
        if element_id in known:
            continue
        next_order += 1
        element = ManifestElement(
            id=element_id,
            type="unknown",
            raw_label=UNSTRUCTURED_PAGE_LABEL,
            reading_order=next_order,
            hierarchy_level=0,
            text=None,
            page_number=number,
            metadata={"unstructured_page": True},
        )
        manifest.elements.append(element)
        page.element_ids.append(element_id)
        manifest.observations.append(
            Observation(
                id=f"observation-{UNSTRUCTURED_PAGE_OBSERVATION_KIND}-{number:04d}",
                kind=UNSTRUCTURED_PAGE_OBSERVATION_KIND,
                severity="warning",
                message=t(MSG_OBSERVATION_PAGE_WITHOUT_STRUCTURE).format(page_number=number),
                target_ids=[element_id],
                evidence={"page_number": number},
            )
        )
        manifest.obligations.append(
            Obligation(
                id=f"obligation-{UNSTRUCTURED_PAGE_OBLIGATION_KIND}-{number:04d}",
                kind=UNSTRUCTURED_PAGE_OBLIGATION_KIND,
                target_ids=[element_id],
                admissible_methods=list(UNSTRUCTURED_PAGE_METHODS),
                method_costs={
                    method: DEFAULT_METHOD_COSTS.get(method, 50)
                    for method in UNSTRUCTURED_PAGE_METHODS
                },
                rationale=t(MSG_OBLIGATION_UNSTRUCTURED_PAGE),
            )
        )
    manifest.summary.element_count = len(manifest.elements)
    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)
    manifest.summary.element_types = dict(
        sorted(Counter(item.type for item in manifest.elements).items())
    )


def _derive_processing_needs(
    elements: list[ManifestElement],
) -> tuple[list[Observation], list[Obligation]]:
    observations: list[Observation] = []
    obligations: list[Obligation] = []

    for element in elements:
        if is_unstructured_page_placeholder(element):
            # Planned by append_unstructured_page_needs, not as an unknown region.
            continue
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
        (element.id, 1 if element.type == "title" else element.hierarchy_level)
        for element in sorted(elements, key=lambda item: item.reading_order)
        if element.type in {"title", "heading"}
    ]
    previous = 0
    for element_id, level in heading_levels:
        invalid_first = not previous and level != 1
        invalid_successor = previous and (level < 2 or level > min(previous + 1, 6))
        if invalid_first or invalid_successor:
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
        bbox = _raw_bbox(element)
        if bbox is None or element.page_number is None or page_sizes is None:
            return None
        size = page_sizes.get(element.page_number)
        if size is None:
            return None
        width, height = size
        if not width or not height:
            return None
        left, top, right, bottom = bbox.left, bbox.top, bbox.right, bbox.bottom
        if is_bottom_left(bbox.coord_origin, top, bottom):
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
