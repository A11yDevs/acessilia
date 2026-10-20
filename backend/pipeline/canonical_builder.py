"""Canonical document builder.

Core migrated to docstruct.canonical; this bridge preserves the backend
contract: uuid-based document ids and LaTeX enrichment through the Toolbox
(``math.convert`` for MathML, ``math.verbalize`` for the spoken text, see
ADR-0007). There is no local fallback: when a capability is unavailable the
formulas keep their LaTeX and the document says so in ``technical_warnings``.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.i18n import t
from backend.tools.formula_tools import label_spoken_formula, normalize_latex
from backend.tools.logger import logger
from backend.tools.toolbox_math_tools import (
    MSG_MATHML_UNAVAILABLE,
    MSG_SPEECH_UNAVAILABLE,
    MathCapabilityUnavailable,
    toolbox_convert_latex,
    toolbox_verbalize_latex,
)
from docstruct.canonical import (  # noqa: F401
    MathEnricher,
    build_canonical_document as _lib_build,
    sanitize_canonical_document as _lib_sanitize,
)


def latex_to_mathml(latex: str) -> str:
    """MathML of a normalized formula via ``math.convert`` ('' if rejected)."""
    return toolbox_convert_latex(latex)


def verbalize_latex(latex: str) -> str:
    """Labelled pt-BR speech of a formula via ``math.verbalize`` ('' if rejected)."""
    return label_spoken_formula(toolbox_verbalize_latex(latex))


class _ToolboxMathEnricher(MathEnricher):
    """Backend enricher: MathML and speech from the Toolbox capabilities.

    The first unavailability of a capability stops its calls for the rest of
    the document, so an outage costs one timeout rather than one per formula,
    and is kept in ``unavailable`` for the document's technical warnings.
    """

    def __init__(self) -> None:
        self.unavailable: dict[str, str] = {}

    def normalize(self, latex: str) -> str:
        return normalize_latex(latex)

    def to_mathml(self, latex: str) -> str:
        # Module-level lookup so tests can monkeypatch
        # canonical_builder.latex_to_mathml (historical contract).
        return self._call("math.convert", latex_to_mathml, latex)

    def verbalize(self, latex: str) -> str:
        return self._call("math.verbalize", verbalize_latex, latex)

    def _call(self, capability: str, function: Any, latex: str) -> str:
        if not latex or capability in self.unavailable:
            return ""
        try:
            return function(latex)
        except MathCapabilityUnavailable as exc:
            logger.warning(
                "{} unavailable; formulas keep their LaTeX ({})", exc.capability, exc
            )
            self.unavailable[capability] = exc.reason
            return ""

    def warnings(self) -> list[str]:
        messages = {
            "math.convert": MSG_MATHML_UNAVAILABLE,
            "math.verbalize": MSG_SPEECH_UNAVAILABLE,
        }
        return [
            t(messages[capability]).format(reason=reason)
            for capability, reason in self.unavailable.items()
        ]


def _backend_id_factory() -> str:
    return f"doc-{uuid4().hex[:12]}"


def build_canonical_document(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Build a canonical document (uuid ids + formula enrichment, as before)."""
    enricher = kwargs.setdefault("math_enricher", _ToolboxMathEnricher())
    kwargs.setdefault("id_factory", _backend_id_factory)
    document = _lib_build(*args, **kwargs)
    if isinstance(enricher, _ToolboxMathEnricher) and enricher.unavailable:
        document.setdefault("technical_warnings", []).extend(enricher.warnings())
    return document


def sanitize_canonical_document(document: dict[str, Any]) -> dict[str, Any]:
    return _lib_sanitize(document)


def _enrich_math_blocks(sections: list[dict[str, Any]]) -> None:
    """Historical internal hook: enriches with the backend enricher."""
    from docstruct.canonical import _enrich_math_blocks as _lib_enrich

    _lib_enrich(sections, _ToolboxMathEnricher())
