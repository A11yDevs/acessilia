from __future__ import annotations

import hashlib
import mimetypes
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docstruct.sections import find_heading_gaps
from docstruct.text.equations import preserve_equation_number
from docstruct.text.latex import has_latex_markup

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
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
from acessilia_core.logger import logger

from acessilia_core.manifest.detectors import (
    inspect_document_needs as _inspect_document_needs,
    normalized_element_bbox as _normalized_element_bbox,
    oriented_bbox as _oriented_bbox,
)
from acessilia_core.manifest.models import (
    Artifact,
    BoundingBox,
    ManifestElement,
    Obligation,
    Observation,
    ProcessingManifest,
)
from acessilia_core.manifest.slides import (
    DEFAULT_FOLD_FIGURE_LABELS,
    DEFAULT_VISUAL_COVERAGE,
    split_across_slides,
    structure_as_slides,
)
from docstruct.placeholders import (
    UNSTRUCTURED_PAGE_FLAG,
    UNSTRUCTURED_PAGE_LABEL as _UNSTRUCTURED_PAGE_LABEL,
    is_unstructured_page_placeholder as _is_placeholder,
)
from docstruct.geometry import (
    ReadingItem,
    order_reading_items,
    reading_role,
)

if TYPE_CHECKING:
    from acessilia_core.manifest.toolbox_extractor import ToolboxExtraction


# Store message IDs here; translate only while building the current request.
# Translation at import time freezes the server locale for all later requests.
OBLIGATION_BY_TYPE = {
    "picture": (
        "describe-image",
        MSG_OBLIGATION_IMAGE,
        ["vision-description", "human-review"],
    ),
    "table": (
        "linearize-table",
        MSG_OBLIGATION_TABLE,
        ["pandoc-table", "human-review"],
    ),
    "formula": (
        "verbalize-formula",
        MSG_OBLIGATION_FORMULA,
        ["mathml", "latex-verbalizer", "human-review"],
    ),
    "code": (
        "preserve-code-semantics",
        MSG_OBLIGATION_CODE,
        ["pandoc-code", "human-review"],
    ),
    "unknown": (
        "review-structure",
        MSG_OBLIGATION_UNKNOWN,
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
#: v2.3 needs the builder emits only for an element of this type, on its own
#: text: once the element is another type they no longer apply, and their
#: methods (``latex-normalizer`` filters formulas) would find no target.
TYPE_BOUND_V23_KINDS: dict[str, frozenset[str]] = {
    "formula": frozenset({"normalize-formula"}),
}

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
    slide_fold_figure_labels: bool = DEFAULT_FOLD_FIGURE_LABELS,
    legacy_unicode_repair: str = "off",
    fusion_judge_max_pages: int = 0,
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
        slide_fold_figure_labels=slide_fold_figure_labels,
        legacy_unicode_repair=legacy_unicode_repair,
        fusion_judge_max_pages=fusion_judge_max_pages,
    )


def separate_equation_number(element: ManifestElement) -> None:
    """Move a formula's trailing equation label into ``metadata.equation_number``.

    A label written as LaTeX (``x=y\\tag{1}``) proves the extractor already
    delivered LaTeX, even when nothing else in the expression is a command:
    ``metadata.latex_markup`` keeps that, so formula recognition still skips
    it once the label is gone.
    """
    if element.type != "formula" or not element.text:
        return
    original = element.text
    element.text = preserve_equation_number(original, element.metadata)
    if (
        element.text != original
        and has_latex_markup(original)
        and not has_latex_markup(element.text)
    ):
        element.metadata["latex_markup"] = True


def _build_from_toolbox_json(
    source_path: Path,
    extraction: ToolboxExtraction,
    *,
    digest: str,
    language: str,
    refine_reading_order: bool = False,
    presentation: bool = False,
    slide_visual_coverage: float = DEFAULT_VISUAL_COVERAGE,
    slide_fold_figure_labels: bool = DEFAULT_FOLD_FIGURE_LABELS,
    legacy_unicode_repair: str = "off",
    fusion_judge_max_pages: int = 0,
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
    for element in manifest.elements:
        separate_equation_number(element)
    secondary = extraction.document.get("secondary_extraction")
    secondary_path = (
        str(secondary["path"])
        if isinstance(secondary, dict) and secondary.get("path")
        else ""
    )
    has_secondary_extraction = bool(secondary_path.strip())
    # skeleton-order reads the file, so it is planned only while the file the
    # extractor wrote is still there; a recorded path alone would plan a
    # method that fails and forces a replan (#298).
    secondary_extraction_readable = (
        has_secondary_extraction and Path(secondary_path).is_file()
    )
    if presentation:
        split_across_slides(manifest)
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
            fold_figure_labels=slide_fold_figure_labels,
            page_fractions=lambda element: _normalized_element_bbox(element, page_sizes),
        )
    observations, obligations = _derive_processing_needs(manifest.elements)
    document_observations, document_obligations = inspect_document_needs(
        manifest.elements,
        page_sizes={
            page.page_number: (page.width, page.height) for page in manifest.pages
        },
        fusion_evidence=extraction.document.get("fusion_evidence"),
        fusion_stats=extraction.document.get("fusion_stats"),
        legacy_unicode_repair=legacy_unicode_repair,
        fusion_judge_max_pages=fusion_judge_max_pages,
        secondary_extraction_available=secondary_extraction_readable,
    )
    observations.extend(document_observations)
    obligations.extend(document_obligations)
    _append_processing_needs(manifest, observations, obligations)
    append_unstructured_page_needs(manifest)
    if has_secondary_extraction:
        manifest.artifacts.append(
            Artifact(
                id=SECONDARY_EXTRACTION_ARTIFACT_ID,
                kind=SECONDARY_EXTRACTION_KIND,
                path=secondary_path,
                media_type="application/json",
                sha256=secondary.get("sha256"),
            )
        )
    return manifest


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
            raw_label=_UNSTRUCTURED_PAGE_LABEL,
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
        kind, msgid, methods = spec
        rationale = t(msgid)
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
    for gap in find_heading_gaps([level for _, level in heading_levels]):
        element_id = heading_levels[gap.index][0]
        suffix = element_id.removeprefix("element-")
        message = t(MSG_HEADING_GAP).format(
            previous=gap.previous_level, level=gap.current_level
        )
        observations.append(
            Observation(
                id=f"observation-heading-gap-{suffix}",
                kind="heading-hierarchy-gap",
                severity="error",
                message=message,
                target_ids=[element_id],
                evidence={
                    "previous_level": gap.previous_level,
                    "current_level": gap.current_level,
                },
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
    return observations, obligations


def inspect_document_needs(
    elements: list[ManifestElement],
    *,
    page_sizes: dict[int, tuple[float | None, float | None]] | None = None,
    fusion_evidence: Any = None,
    fusion_stats: Any = None,
    fusion_judge_max_pages: int = 0,
    legacy_unicode_repair: str = "off",
    secondary_extraction_available: bool = False,
) -> tuple[list[Observation], list[Obligation]]:
    """Emit document-level needs when deterministic checks or fusion evidence support them.

    ``fusion_judge_max_pages`` caps how many pages get the VLM judge
    (the run's ``FusionConfig``; 0, no judge). ``legacy_unicode_repair`` is
    ``off``/``detect``/``repair``, the run's ``DocumentConfig`` value; only
    ``repair`` emits the obligation, while ``detect`` keeps the observation.
    ``skeleton-order`` is admissible only when the secondary extraction file
    the extractor recorded for this document can be read.
    """
    return _inspect_document_needs(
        elements,
        obligation_specs=V23_OBLIGATION_BY_KIND,
        method_costs=DEFAULT_METHOD_COSTS,
        page_sizes=page_sizes,
        fusion_evidence=fusion_evidence,
        fusion_stats=fusion_stats,
        fusion_judge_max_pages=fusion_judge_max_pages,
        legacy_unicode_repair=legacy_unicode_repair,
        secondary_extraction_available=secondary_extraction_available,
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

    The standard processing need associated with the reclassified element is
    replaced, and the v2.3 needs bound to its previous type
    (``TYPE_BOUND_V23_KINDS``, such as ``normalize-formula``) are dropped;
    every other observation/obligation (e.g. the v2.3 needs derived from
    dual-provider fusion evidence) is kept untouched instead of rebuilding the
    complete list.
    """
    if previous_type == element.type:
        return

    previous_spec = OBLIGATION_BY_TYPE.get(previous_type)
    current_spec = OBLIGATION_BY_TYPE.get(element.type)
    if current_spec is None:
        return

    current_kind, msgid, methods = current_spec
    rationale = t(msgid)
    previous_kind = previous_spec[0] if previous_spec is not None else None
    previous_observation_kind = (
        f"{previous_type}-requires-processing" if previous_spec is not None else None
    )
    current_observation_kind = f"{element.type}-requires-processing"
    bound_kinds = TYPE_BOUND_V23_KINDS.get(previous_type, frozenset())
    bound_observation_kinds = {f"{kind}-detected" for kind in bound_kinds}
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
        if targets_only_element and (
            (previous_kind is not None and obligation.kind == previous_kind)
            or obligation.kind in bound_kinds
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
        if targets_only_element and (
            (
                previous_observation_kind is not None
                and observation.kind == previous_observation_kind
            )
            or observation.kind in bound_observation_kinds
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
