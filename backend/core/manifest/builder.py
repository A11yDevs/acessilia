from __future__ import annotations

import hashlib
import mimetypes
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.i18n import t
from backend.log_messages import (
    LOG_MANIFEST_STRUCTURAL_CONTAINER_SKIPPED,
    MSG_HEADING_GAP,
    MSG_OBLIGATION_CODE,
    MSG_OBLIGATION_FORMULA,
    MSG_OBLIGATION_IMAGE,
    MSG_OBLIGATION_TABLE,
    MSG_OBLIGATION_UNKNOWN,
    MSG_OBLIGATION_UNSTRUCTURED_PAGE,
    MSG_OBSERVATION_PAGE_WITHOUT_STRUCTURE,
)
from backend.tools.logger import logger

from backend.core.manifest.models import (
    Artifact,
    BoundingBox,
    ManifestElement,
    Obligation,
    Observation,
    ProcessingManifest,
)
from backend.core.manifest.slides import DEFAULT_VISUAL_COVERAGE, structure_as_slides
from docstruct.placeholders import (
    UNSTRUCTURED_PAGE_FLAG,
    UNSTRUCTURED_PAGE_LABEL,
    is_unstructured_page_placeholder as _is_placeholder,
)
from docstruct.geometry import (
    OrientedBox,
    ReadingItem,
    order_reading_items,
    reading_role,
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
    "unicode-repair": 5,
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
    "repair-legacy-unicode": (
        "Texto extraído de PDF legado contém Unicode mal composto (NFD ou i sem ponto).",
        ["unicode-repair", "human-review"],
    ),
    "inspect-unstructured-page": (
        "Página sem estrutura extraída exige inspeção visual.",
        ["vision-page-inspection", "human-review"],
    ),
}

#: Artifact holding the secondary provider's extraction when FUSION_MODE=dual;
#: the v2.3 methods that choose between providers read it.
#: A page the extractor returned without any element gets a placeholder element
#: (``docstruct.placeholders``), an observation and a critical obligation: the
#: page is inspected visually and either described or accepted as blank.
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
    presentation: bool = False,
    slide_visual_coverage: float = DEFAULT_VISUAL_COVERAGE,
) -> ProcessingManifest:
    """Builds the processing manifest from the Toolbox structural extraction.

    The Toolbox is the only extractor (docs/adr/0003): ``extraction.document``
    is its JSON response, whose elements already carry callouts, code text and
    table structure. This core adds its own planning policy on top. A
    ``presentation`` is structured slide by slide (``slides.structure_as_slides``)
    before its processing needs are derived.

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
        presentation=presentation,
        slide_visual_coverage=slide_visual_coverage,
    )


def _build_from_toolbox_json(
    source_path: Path,
    extraction: ToolboxExtraction,
    *,
    digest: str,
    language: str,
    refine_reading_order: bool = False,
    presentation: bool = False,
    slide_visual_coverage: float = DEFAULT_VISUAL_COVERAGE,
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
    if presentation:
        page_sizes = {page.page_number: (page.width, page.height) for page in manifest.pages}
        structure_as_slides(
            manifest,
            visual_coverage=slide_visual_coverage,
            page_fractions=lambda element: _normalized_element_bbox(element, page_sizes),
        )
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


def _oriented_bbox(element: ManifestElement) -> OrientedBox | None:
    bbox = _raw_bbox(element)
    if bbox is None:
        return None
    return OrientedBox(bbox.left, bbox.top, bbox.right, bbox.bottom, bbox.coord_origin)


def _element_bbox(element: ManifestElement) -> tuple[float, float, float, float] | None:
    """Element box with the y axis growing downwards, whatever the source origin.

    See ``docstruct.geometry.OrientedBox.top_down``: only differences and
    orderings are meaningful. ``_normalized_element_bbox`` gives page
    fractions instead.
    """
    box = _oriented_bbox(element)
    return box.top_down() if box is not None else None


def _refine_reading_order(elements: list[ManifestElement]) -> list[ManifestElement]:
    """Reorder elements as ``docstruct.geometry.order_reading_items`` reads them.

    Headers stay at the top of their page, footers and page numbers at the
    bottom, and the body follows its columns. ``reading_order`` is renumbered
    from 1. The same element objects are returned.
    """
    if not elements:
        return elements

    by_id = {element.id: element for element in elements}
    order = order_reading_items(
        [
            ReadingItem(
                key=element.id,
                page=element.page_number,
                role=reading_role(str(element.type), str(element.raw_label)),
                box=_oriented_bbox(element),
                rank=element.reading_order,
            )
            for element in elements
        ]
    )
    refined = [by_id[key] for key in order]
    for index, element in enumerate(refined, start=1):
        element.reading_order = index
    return refined


def is_unstructured_page_placeholder(element: ManifestElement) -> bool:
    """Whether ``element`` stands for a page the extractor left without structure."""
    return _is_placeholder(element.raw_label, element.metadata)


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
            metadata={UNSTRUCTURED_PAGE_FLAG: True},
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


def _is_structural_container(
    element: ManifestElement, parent_ids: set[str]
) -> bool:
    """An unknown element that only groups others and has no region of its own.

    The Toolbox maps Docling's group labels other than lists (``key_value_area``,
    ``form_area``) to ``unknown`` instead of ``group``. Such a node has no
    provenance, so region inspection cannot render it and its review-structure
    obligation could only be escalated, failing the job; its children carry the
    content and get their own obligations. An unknown leaf, or one with a
    region, is still reviewed.
    """
    return (
        element.type == "unknown"
        and not element.provenance
        and element.id in parent_ids
    )


def _derive_processing_needs(
    elements: list[ManifestElement],
) -> tuple[list[Observation], list[Obligation]]:
    observations: list[Observation] = []
    obligations: list[Obligation] = []
    parent_ids: set[str] = {
        element.parent_id for element in elements if element.parent_id
    }

    for element in elements:
        if is_unstructured_page_placeholder(element):
            # Planned by append_unstructured_page_needs, not as an unknown region.
            continue
        if _is_structural_container(element, parent_ids):
            logger.debug(
                t(LOG_MANIFEST_STRUCTURAL_CONTAINER_SKIPPED).format(
                    element_id=element.id, raw_label=element.raw_label
                )
            )
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
    fusion_judge_max_pages: int | None = None,
    legacy_unicode_repair: str | None = None,
) -> tuple[list[Observation], list[Obligation]]:
    """Emit v2.3 needs only when deterministic checks or fusion evidence support them.

    ``fusion_judge_max_pages`` caps how many pages get the VLM judge
    (FUSION_JUDGE_MAX_PAGES when None). ``legacy_unicode_repair`` is
    ``off``/``detect``/``repair`` (LEGACY_UNICODE_REPAIR when None); only
    ``repair`` emits the obligation, while ``detect`` keeps the observation.
    """
    from docstruct.fusion.line_numbers import extract_line_numbers
    from docstruct.fusion.tailjoin import join_tail, page_number_position, tailjoin3
    from docstruct.fusion.types import DiffBlock
    from docstruct.fusion.verse import verse_blocks
    from docstruct.fusion.xycut import xycut_order
    from docstruct.text.latex import normalize_latex
    from docstruct.text.norm_fix import norm_fix
    from docstruct.text.unicode_repair import detect_legacy_unicode

    candidates: list[
        tuple[str, list[ManifestElement], dict[str, Any], list[str] | None, bool]
    ] = []
    by_page: dict[int | None, list[ManifestElement]] = {}
    for element in elements:
        by_page.setdefault(element.page_number, []).append(element)

    def add(
        kind: str,
        targets: list[ManifestElement],
        evidence: dict[str, Any],
        methods: list[str] | None = None,
        *,
        obligation: bool = True,
    ) -> None:
        valid_targets = [item for item in targets if item.id]
        if valid_targets:
            candidates.append((kind, valid_targets, evidence, methods, obligation))

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

    if legacy_unicode_repair is None:
        from backend.config.settings import settings

        legacy_unicode_repair = settings.legacy_unicode_repair
    unicode_mode = str(legacy_unicode_repair or "off").strip().lower()
    if unicode_mode not in {"off", "detect", "repair"}:
        unicode_mode = "off"
    if unicode_mode != "off":
        legacy_targets: list[ManifestElement] = []
        legacy_evidence: Counter = Counter()
        for element in elements:
            if element.type not in {
                "paragraph",
                "heading",
                "title",
                "list_item",
                "caption",
                "footnote",
            } or not element.text:
                continue
            detection = detect_legacy_unicode(element.text)
            if not detection.has_signal:
                continue
            repairable = bool(detection.combining_runs or detection.dotless)
            # Phase B rewrites only NFC and dotless-i; spacing diacritics stay
            # report-only until font evidence exists.
            if unicode_mode == "repair" and not repairable:
                continue
            legacy_targets.append(element)
            legacy_evidence["elements"] += 1
            legacy_evidence["combining_runs"] += detection.combining_runs
            legacy_evidence["combining_marks"] += detection.combining_marks
            legacy_evidence["dotless"] += detection.dotless
            legacy_evidence["spacing_diacritics"] += detection.spacing_diacritics
            legacy_evidence["replacement_characters"] += (
                detection.replacement_characters
            )
        if legacy_targets:
            add(
                "repair-legacy-unicode",
                legacy_targets,
                dict(legacy_evidence),
                obligation=unicode_mode == "repair",
            )

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
    if fusion_judge_max_pages is None:
        from backend.config.settings import settings

        fusion_judge_max_pages = settings.fusion_judge_max_pages
    if isinstance(fusion_evidence, dict):
        pages = fusion_evidence.get("pages")
        if isinstance(pages, list):
            entries: list[tuple[int, dict[str, Any], list[ManifestElement]]] = []
            for page_data in pages:
                if not isinstance(page_data, dict):
                    continue
                page_stats = page_data.get("stats")
                page_number = page_data.get("page_number")
                page_targets = by_page.get(page_number, [])
                if not isinstance(page_stats, dict) or not page_targets:
                    continue
                entries.append((page_number, page_stats, page_targets))
            judged = _pages_for_vlm_judge(entries, fusion_judge_max_pages)
            fused_targets: list[ManifestElement] = []
            fused_pages: list[int] = []
            for page_number, page_stats, page_targets in entries:
                _add_fusion_observations(
                    add,
                    page_targets,
                    page_stats,
                    page_number,
                    judge=page_number in judged,
                )
                if page_stats.get("provider_divergence"):
                    fused_targets.extend(page_targets)
                    fused_pages.append(page_number)
            # One obligation per document: each fuse-providers step works on the
            # whole document, so one per page repeated the same extraction.
            if fused_targets:
                add("fuse-providers", fused_targets, {"pages": fused_pages})
    elif isinstance(stats, dict):
        targets = [element for element in elements if element.text]
        if targets:
            _add_fusion_observations(
                add,
                targets,
                stats,
                None,
                judge=fusion_judge_max_pages > 0 and _needs_vlm_judge(stats),
            )
            if stats.get("provider_divergence"):
                add("fuse-providers", targets, {"page_number": None, "fusion_stats": stats})

    observations: list[Observation] = []
    obligations: list[Obligation] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for kind, targets, evidence, methods_override, emit_obligation in candidates:
        target_ids = list(dict.fromkeys(item.id for item in targets))
        key = (kind, tuple(target_ids))
        if key in seen:
            continue
        seen.add(key)
        rationale, methods = V23_OBLIGATION_BY_KIND[kind]
        methods = methods_override or methods
        suffix = _obligation_suffix(target_ids)
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
        if not emit_obligation:
            continue
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


#: Longest id suffix spelled out from the target ids; past it the suffix is a
#: digest, since a document-level obligation targets every element of every
#: divergent page and its id goes into the manifest, the PDDL problem and plan.
MAX_ID_SUFFIX = 80


def _obligation_suffix(target_ids: list[str]) -> str:
    suffix = "-".join(item.removeprefix("element-") for item in target_ids)
    if len(suffix) <= MAX_ID_SUFFIX:
        return suffix
    digest = hashlib.sha256("\n".join(target_ids).encode("utf-8")).hexdigest()
    return f"{len(target_ids)}-targets-{digest[:12]}"


#: Methods of an adjudicate-page obligation. The deterministic router already
#: ran on the evidence (``route``), and re-running it as agreement-rule would
#: only repeat its answer, so the obligation goes straight to the VLM judge.
VLM_JUDGE_METHODS = ["vlm-pairwise-judge", "human-review"]


def _needs_vlm_judge(stats: dict[str, Any]) -> bool:
    """Whether the deterministic router leaves the page to the VLM judge.

    ``decide_v1`` settles a page from a structural fact (one side nearly empty,
    a table or formula only one provider found) or keeps docling by default;
    only its preference rules, where both providers have a table or a formula
    (``both_table->mineru``, ``both_formula->mineru``), are worth a model call,
    and only when the two pages differ (``provider_divergence``, over all the
    page's content: ``text_divergence`` leaves tables and formulas out, so a
    page whose prose matches and whose tables differ would never be judged).
    Evidence recorded before the router ran has no ``route`` and stays eligible
    on ``text_divergence``, as before.
    """
    route = stats.get("route")
    if route is None:
        return bool(stats.get("text_divergence"))
    return (
        bool(stats.get("provider_divergence"))
        and route != "docling"
        and str(stats.get("route_reason", "")).startswith("both_")
    )


def _pages_for_vlm_judge(
    entries: list[tuple[int, dict[str, Any], list[ManifestElement]]],
    budget: int,
) -> set[int]:
    """The ``budget`` ambiguous pages the providers disagree on the most.

    Ranked by ``similarity``, the measure ``_needs_vlm_judge`` gates on
    (``text_similarity`` for evidence recorded before the router ran).
    """
    ambiguous = sorted(
        (
            float(
                stats.get("similarity" if "route" in stats else "text_similarity", 0.0)
            ),
            page_number,
        )
        for page_number, stats, _ in entries
        if isinstance(page_number, int) and _needs_vlm_judge(stats)
    )
    return {page_number for _, page_number in ambiguous[: max(budget, 0)]}


def _add_fusion_observations(
    add: Any,
    targets: list[ManifestElement],
    stats: dict[str, Any],
    page_number: int | None,
    *,
    judge: bool,
) -> None:
    """Per-page fusion needs; ``fuse-providers`` is emitted once by the caller."""
    if not stats:
        return
    if judge:
        add(
            "adjudicate-page",
            targets,
            {"page_number": page_number, "fusion_stats": stats},
            VLM_JUDGE_METHODS,
        )
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
        box = _oriented_bbox(element)
        if box is None or element.page_number is None or page_sizes is None:
            return None
        size = page_sizes.get(element.page_number)
        if size is None:
            return None
        return box.page_fractions(*size)


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
