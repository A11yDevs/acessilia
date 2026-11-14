"""The method registry: which handler runs each obligation method.

``METHOD_HANDLERS`` maps every method the executor can run to its handler;
``build_method_registry`` registers them. The registry looks a handler up by
its method's name, so the table's order does not change what runs; it keeps
the order ``_build_executor`` used, for the reader. A
method the manifest can require but that is absent here is reported to the
planner as unavailable: no step only fails. Gathered from the orchestrator's
``DETERMINISTIC_METHOD_HANDLERS`` and the registrations of its
``_build_executor`` (#402, phase 3, step 6), without changing a single
method-handler pair.
"""

from __future__ import annotations

from collections.abc import Callable

from backend.core.execution.executor import MethodRegistry
from backend.core.execution.models import MethodResult
from backend.core.manifest.models import ProcessingManifest
from backend.core.pipeline.handlers.content import (
    _handle_pandoc_code_method,
    _handle_pandoc_table_method,
    _handle_vision_description_method,
)
from backend.core.pipeline.handlers.formula import (
    _handle_latex_normalizer_method,
    _handle_latex_verbalizer_method,
    _handle_mathml_method,
)
from backend.core.pipeline.handlers.fusion import (
    _handle_agreement_rule_method,
    _handle_dual_provider_fusion_method,
    _handle_single_provider_method,
    _handle_table_smart_fusion_method,
)
from backend.core.pipeline.handlers.inspection import (
    _handle_pymupdf_region_method,
    _handle_vision_page_inspection_method,
)
from backend.core.pipeline.handlers.judge import (
    _handle_vlm_pairwise_judge_method,
)
from backend.core.pipeline.handlers.order import (
    _handle_skeleton_order_method,
    _handle_xycut_order_method,
)
from backend.core.pipeline.handlers.review import (
    _handle_human_review_method,
)
from backend.core.pipeline.handlers.text import (
    _handle_chunk_verse_method,
    _handle_deterministic_heading_repair_method,
    _handle_extract_line_numbers_method,
    _handle_norm_fix_method,
    _handle_repetition_guard_method,
    _handle_tailjoin_method,
    _handle_unicode_repair_method,
)

#: Method name -> handler.
METHOD_HANDLERS: dict[str, Callable[[ProcessingManifest, str], MethodResult]] = {
    # Methods that call a Toolbox capability or a model and fail explicitly
    # when it is unavailable, and the provider fusion and choice.
    "mathml": _handle_mathml_method,
    "latex-verbalizer": _handle_latex_verbalizer_method,
    "dual-provider-fusion": _handle_dual_provider_fusion_method,
    "single-provider": _handle_single_provider_method,
    "vlm-pairwise-judge": _handle_vlm_pairwise_judge_method,
    # Work done before planning, deterministic work, or one vision model call
    # (pymupdf-region, vision-page-inspection).
    "vision-description": _handle_vision_description_method,
    "pandoc-table": _handle_pandoc_table_method,
    "pandoc-code": _handle_pandoc_code_method,
    "pymupdf-region": _handle_pymupdf_region_method,
    "vision-page-inspection": _handle_vision_page_inspection_method,
    "latex-normalizer": _handle_latex_normalizer_method,
    "norm-fix": _handle_norm_fix_method,
    "unicode-repair": _handle_unicode_repair_method,
    "rep-guard": _handle_repetition_guard_method,
    "line-number-extractor": _handle_extract_line_numbers_method,
    "verse-chunker": _handle_chunk_verse_method,
    "tailjoin": _handle_tailjoin_method,
    "tailjoin-positioned": _handle_tailjoin_method,
    "xycut-order": _handle_xycut_order_method,
    "skeleton-order": _handle_skeleton_order_method,
    "table-smart-fusion": _handle_table_smart_fusion_method,
    "agreement-rule": _handle_agreement_rule_method,
    "deterministic-heading-repair": _handle_deterministic_heading_repair_method,
    # `human-review` has its own semantics: it is the terminal escalation the
    # pipeline performs when no automated method can satisfy an obligation.
    "human-review": _handle_human_review_method,
}


def build_method_registry() -> MethodRegistry:
    """A ``MethodRegistry`` with every method of ``METHOD_HANDLERS``."""
    registry = MethodRegistry()
    for method, handler in METHOD_HANDLERS.items():
        registry.register(method, handler)
    return registry


__all__ = ["METHOD_HANDLERS", "build_method_registry"]
