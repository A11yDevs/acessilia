"""Canonical document builder.

Core migrated to docstruct.canonical; this bridge preserves the backend
contract: uuid-based document ids and LaTeX enrichment through the Toolbox
(``math.convert`` for MathML, ``math.verbalize`` for the spoken text, see
ADR-0007). There is no local fallback: when a capability is unavailable the
formulas keep their LaTeX and the document says so in ``technical_warnings``,
as it does for formulas whose LaTeX the Toolbox rejected.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.i18n import t
from backend.tools.formula_tools import label_spoken_formula, normalize_latex
from backend.tools.logger import logger
from backend.tools.toolbox_math_tools import (
    MSG_MATHML_REJECTED,
    MSG_MATHML_UNAVAILABLE,
    MSG_SPEECH_REJECTED,
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
    Formulas the Toolbox answered with nothing (rejected LaTeX) are counted in
    ``rejected`` so the degradation is reported too, not only logged.

    ``MathCapabilityUnavailable`` is the only failure the conversion functions
    are expected to raise: the SDK maps every transport and HTTP error to a
    ``ToolboxError``, so anything else is a bug and deliberately fails the build.
    """

    def __init__(self) -> None:
        self.unavailable: dict[str, str] = {}
        self.rejected: dict[str, int] = {}

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
            result = function(latex)
        except MathCapabilityUnavailable as exc:
            logger.warning(
                "{} unavailable; formulas keep their LaTeX ({})", exc.capability, exc
            )
            self.unavailable[capability] = exc.reason
            return ""
        if not result:
            self.rejected[capability] = self.rejected.get(capability, 0) + 1
        return result

    def warnings(self) -> list[str]:
        unavailable = {
            "math.convert": MSG_MATHML_UNAVAILABLE,
            "math.verbalize": MSG_SPEECH_UNAVAILABLE,
        }
        rejected = {
            "math.convert": MSG_MATHML_REJECTED,
            "math.verbalize": MSG_SPEECH_REJECTED,
        }
        return [
            t(unavailable[capability]).format(reason=reason)
            for capability, reason in self.unavailable.items()
        ] + [
            t(rejected[capability]).format(count=count)
            for capability, count in self.rejected.items()
        ]


def _backend_id_factory() -> str:
    return f"doc-{uuid4().hex[:12]}"


def build_canonical_document(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Build a canonical document (uuid ids + formula enrichment, as before)."""
    if "math_enricher" not in kwargs:
        kwargs["math_enricher"] = _ToolboxMathEnricher()
    enricher = kwargs["math_enricher"]
    kwargs.setdefault("id_factory", _backend_id_factory)
    document = _lib_build(*args, **kwargs)
    # A caller-supplied enricher owns its warnings; only ours reports them here.
    if isinstance(enricher, _ToolboxMathEnricher):
        if warnings := enricher.warnings():
            document.setdefault("technical_warnings", []).extend(warnings)
    return document


def sanitize_canonical_document(document: dict[str, Any]) -> dict[str, Any]:
    return _lib_sanitize(document)


def _enrich_math_blocks(sections: list[dict[str, Any]]) -> None:
    """Historical internal hook: enriches with the backend enricher.

    For tests only: the enricher's unavailability and rejection warnings are
    discarded. Real callers go through ``build_canonical_document``, which
    reports them in ``technical_warnings``.
    """
    from docstruct.canonical import _enrich_math_blocks as _lib_enrich

    _lib_enrich(sections, _ToolboxMathEnricher())
