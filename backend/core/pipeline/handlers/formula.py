"""Formula handlers: MathML, spoken text and normalized LaTeX for formula obligations.

``mathml`` and ``latex-verbalizer`` convert and speak each target formula
through the Toolbox (``toolbox_convert_latex`` and ``toolbox_verbalize_latex``,
which call the SDK's formula steps, ADR-0017); an unavailable capability fails
the method explicitly so the executor can try another one or replan. Both mark
implicit products with the variables the whole document uses, as the canonical
build does. ``latex-normalizer`` normalizes the LaTeX in place. Moved verbatim
from the PDDL orchestrator once ADR-0017 was accepted (#402, phase 3, step 6).
"""

from __future__ import annotations

from docstruct.text.implicit_products import (
    implicit_product_variables,
    mark_implicit_products,
)
from docstruct.text.math_spans import block_prose, inline_math_sources

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.core.pipeline.elements import (
    _element_to_block,
    _text_kept_by_picture,
)
from backend.core.pipeline.handlers import messages as step_messages
from backend.core.pipeline.handlers.common import (
    _target_elements,
)
from backend.core.pipeline.obligations import (
    _formula_elements_for_obligation,
)
from backend.i18n import n, t
from backend.tools.formula_tools import label_spoken_formula, normalize_latex
from backend.tools.logger import logger
from backend.tools.toolbox_math_tools import (
    MSG_MATHML_UNAVAILABLE,
    MSG_SPEECH_UNAVAILABLE,
    MathCapabilityUnavailable,
    toolbox_convert_latex,
    toolbox_verbalize_latex,
)


def _implicit_product_variables(manifest: ProcessingManifest) -> frozenset[str]:
    """The letters the document uses as variables, from all its formulas.

    Read from every formula element and every inline span of the manifest, the
    same sources the canonical build reads, so a formula converted here and
    one converted there mark the same products.
    """
    sources: list[str] = []
    for element in manifest.elements:
        blocks = [
            _element_to_block(item)
            for item in [element, *_text_kept_by_picture(element)]
        ]
        for block in blocks:
            if block.get("type") == "math":
                sources.append(str(block.get("text") or ""))
            for text in block_prose(block):
                sources.extend(inline_math_sources(text))
    return implicit_product_variables(sources)


def _handle_mathml_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Convert the target formulas' LaTeX to MathML (metadata.mathml) via math.convert.

    An unavailable math.convert fails the method explicitly (no local
    conversion, ADR-0007), so the executor can try another method or replan.
    """
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(success=False, validated=False, message=t(step_messages.MSG_MATH_NO_FORMULA))
    converted = 0
    variables = _implicit_product_variables(manifest)
    for element in elements:
        latex = mark_implicit_products(normalize_latex(element.text or ""), variables)
        try:
            mathml = toolbox_convert_latex(latex) if latex else ""
        except MathCapabilityUnavailable as exc:
            logger.warning("Handler mathml: {}", exc)
            return MethodResult(
                success=False,
                validated=False,
                message=t(MSG_MATHML_UNAVAILABLE).format(reason=exc.reason),
            )
        if mathml:
            element.metadata["mathml"] = mathml
            converted += 1
    if converted == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=n(*step_messages.MSG_MATHML_GENERATED, converted).format(count=converted),
        )
    return MethodResult(
        success=False,
        validated=False,
        message=n(*step_messages.MSG_MATHML_GENERATED_PARTIAL, len(elements)).format(
            done=converted, total=len(elements)
        ),
    )


def _handle_latex_verbalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Generate the pt-BR verbalization of the formulas (metadata.verbalization) via math.verbalize.

    An unavailable math.verbalize fails the method explicitly (no local
    verbalizer, ADR-0007).
    """
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(success=False, validated=False, message=t(step_messages.MSG_MATH_NO_FORMULA))
    verbalized = 0
    variables = _implicit_product_variables(manifest)
    for element in elements:
        latex = mark_implicit_products(normalize_latex(element.text or ""), variables)
        try:
            spoken = label_spoken_formula(toolbox_verbalize_latex(latex)) if latex else ""
        except MathCapabilityUnavailable as exc:
            logger.warning("Handler latex-verbalizer: {}", exc)
            return MethodResult(
                success=False,
                validated=False,
                message=t(MSG_SPEECH_UNAVAILABLE).format(reason=exc.reason),
            )
        if spoken:
            element.metadata["verbalization"] = spoken
            verbalized += 1
    if verbalized == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=n(*step_messages.MSG_VERBALIZATION_GENERATED, verbalized).format(
                count=verbalized
            ),
        )
    return MethodResult(
        success=False,
        validated=False,
        message=n(*step_messages.MSG_VERBALIZATION_GENERATED_PARTIAL, len(elements)).format(
            done=verbalized, total=len(elements)
        ),
    )


def _handle_latex_normalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize the LaTeX of every formula target in place."""
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "formula"
    ]
    if not elements:
        return MethodResult(success=False, validated=False, message=t(step_messages.MSG_MATH_NO_FORMULA))

    normalized = 0
    for element in elements:
        cleaned = normalize_latex(element.text or "")
        if not cleaned:
            continue
        element.metadata["latex_normalized"] = cleaned
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=n(*step_messages.MSG_LATEX_NORMALIZED_PARTIAL, len(elements)).format(
                done=normalized, total=len(elements)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=n(*step_messages.MSG_LATEX_NORMALIZED, normalized).format(
            count=normalized
        ),
    )
