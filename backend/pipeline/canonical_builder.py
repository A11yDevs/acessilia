"""Canonical document builder.

Core migrated to docstruct.canonical; this bridge preserves the backend
contract: uuid-based document ids and LaTeX enrichment via formula_tools
(latex2mathml in-process + pt-BR verbalization fallback).
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.tools.formula_tools import (  # noqa: F401
    latex_to_mathml,
    normalize_latex,
    verbalize_latex_fallback,
)
from docstruct.canonical import (  # noqa: F401
    MathEnricher,
    build_canonical_document as _lib_build,
    sanitize_canonical_document as _lib_sanitize,
)


class _FormulaToolsEnricher(MathEnricher):
    """Backend enricher: latex2mathml (in-process) + pt-BR verbalization."""

    def normalize(self, latex: str) -> str:
        return normalize_latex(latex)

    def to_mathml(self, latex: str) -> str:
        # Module-level lookup so tests can monkeypatch
        # canonical_builder.latex_to_mathml (historical contract).
        return latex_to_mathml(latex)

    def verbalize(self, latex: str) -> str:
        return verbalize_latex_fallback(latex)


def _backend_id_factory() -> str:
    return f"doc-{uuid4().hex[:12]}"


def build_canonical_document(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Build a canonical document (uuid ids + formula enrichment, as before)."""
    kwargs.setdefault("math_enricher", _FormulaToolsEnricher())
    kwargs.setdefault("id_factory", _backend_id_factory)
    return _lib_build(*args, **kwargs)


def sanitize_canonical_document(document: dict[str, Any]) -> dict[str, Any]:
    return _lib_sanitize(document)


def _enrich_math_blocks(sections: list[dict[str, Any]]) -> None:
    """Historical internal hook: enriches with the backend enricher."""
    from docstruct.canonical import _enrich_math_blocks as _lib_enrich

    _lib_enrich(sections, _FormulaToolsEnricher())
