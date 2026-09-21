"""Fusion agent — Agno tools over the docstruct fusion/validation stack.

Phase 5 of the docstruct plan. Follows the ``InformationalStructuralAgent``
pattern: each capability has a deterministic ``process_*`` method (pure,
testable, no LLM) plus a thin tool envelope that returns JSON-serializable
dicts for the Agno agent.

Tools exposed:
- ``fuse_providers`` — merge two toolbox providers via ``docstruct.fusion``.
- ``audit_document`` — run the canonical-document audit (validation findings).
- ``classify_block`` — classify a region/block via ``docstruct.regions``.
- ``needs_reinfer`` — decide whether a region needs re-inference (vision or
  orientation correction).

The deterministic methods live here so they can be unit-tested without Agno
installed; the tool envelopes are only wired into the Agno agent when the
optional stack is available (see ``backend.core.agno_support.build_agent``).

Design note (tool envelope vs core): the Agno tool envelopes intentionally do
NOT serialize ``image_bytes`` — they reconstruct a ``Region`` with
``image_bytes=None``. This is a conscious decision: binary payloads should not
cross tool-call boundaries. For future multimodal decisions, pass a persistent
reference (``artifact_id`` / ``image_ref`` / ``crop_path`` / object-storage URI)
instead of raw bytes.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.core.agno_support import build_agent
from docstruct.regions.classify import (
    classify_region,
    region_needs_vision,
)
from docstruct.types import Region
from docstruct.validation import audit_canonical_document


class FusionAgent:
    """Agno agent whose tools wrap the deterministic fusion/audit stack."""

    def __init__(
        self,
        *,
        model: Any | None = None,
    ) -> None:
        self.agent = build_agent(
            name="Agente de Fusão",
            instructions=(
                "Use as ferramentas fornecidas para fundir, auditar e "
                "classificar documentos de forma determinística.",
                "Não invente resultados: retorne somente o que as ferramentas "
                "produzem.",
                "Prefira a fusão dual-provider quando a qualidade do texto "
                "for crítica.",
            ),
            tools=(
                self.fuse_providers,
                self.audit_document,
                self.classify_block,
                self.needs_reinfer,
            ),
            model=model,
        )

    # ── Deterministic core (unit-testable without Agno) ──────────────────

    def process_fuse_providers(
        self,
        document_path: Path | str,
        *,
        language: str = "pt-BR",
        primary_provider: str | None = None,
        secondary_provider: str | None = None,
    ) -> dict[str, Any]:
        """Merge two toolbox providers into a single fused payload.

        Delegates to ``backend.pipeline.fusion.extract_fused`` (the only layer
        that knows both the toolbox and the lib). Returns the fused payload in
        the same shape as ``extract_structure``.
        """
        from backend.pipeline.fusion import extract_fused

        return asyncio.run(
            extract_fused(
                Path(document_path),
                language=language,
                primary_provider=primary_provider,
                secondary_provider=secondary_provider,
            )
        )

    def process_audit_document(
        self,
        document: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Audit a canonical document and return grouped findings."""
        return audit_canonical_document(document)

    def process_classify_block(
        self,
        region: Region,
    ) -> str:
        """Classify a region into a docstruct category."""
        return classify_region(region)

    def process_needs_reinfer(
        self,
        region: Region,
    ) -> bool:
        """Decide whether a region needs re-inference (vision or orientation)."""
        classification = classify_region(region)
        return region_needs_vision(classification)

    # ── Tool envelopes (JSON-serializable for Agno) ───────────────────────

    def fuse_providers(
        self,
        document_path: str,
        language: str = "pt-BR",
        primary_provider: str | None = None,
        secondary_provider: str | None = None,
    ) -> dict[str, Any]:
        """Funde dois providers de extração em um único payload.

        Args:
            document_path (str): Caminho do documento a processar.
            language (str): Idioma do documento (default "pt-BR").
            primary_provider (str | None): Provider primário (default: config).
            secondary_provider (str | None): Provider secundário (default: config).

        Returns:
            dict: Payload fundido com ``document.elements`` e ``fusion_stats``.
        """
        return self.process_fuse_providers(
            Path(document_path),
            language=language,
            primary_provider=primary_provider,
            secondary_provider=secondary_provider,
        )

    def audit_document(
        self,
        document: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Audita um documento canônico e retorna achados agrupados.

        Args:
            document (dict): Documento canônico (schema_version, sections, ...).

        Returns:
            dict: Mapeamento ``{"ERROR": [...], "WARNING": [...], "INFO": [...]}``.
        """
        return self.process_audit_document(document)

    def classify_block(
        self,
        region: dict[str, Any],
    ) -> dict[str, Any]:
        """Classifica uma região em uma categoria docstruct.

        Args:
            region (dict): Região serializada (bbox, type, text, confidence,
                page_num, metadata).

        Returns:
            dict: ``{"classification": str, "needs_vision": bool}``.
        """
        parsed = Region(
            bbox=tuple(region["bbox"]),
            type=region.get("type", "unknown"),
            text=region.get("text", ""),
            image_bytes=None,
            confidence=region.get("confidence", 0.0),
            page_num=region.get("page_num", 1),
            metadata=region.get("metadata", {}),
        )
        classification = self.process_classify_block(parsed)
        return {
            "classification": classification,
            "needs_vision": region_needs_vision(classification),
        }

    def needs_reinfer(
        self,
        region: dict[str, Any],
    ) -> dict[str, Any]:
        """Decide se uma região precisa de re-inferência.

        Args:
            region (dict): Região serializada (mesmo formato de ``classify_block``).

        Returns:
            dict: ``{"needs_reinfer": bool, "reason": str}``.
        """
        parsed = Region(
            bbox=tuple(region["bbox"]),
            type=region.get("type", "unknown"),
            text=region.get("text", ""),
            image_bytes=None,
            confidence=region.get("confidence", 0.0),
            page_num=region.get("page_num", 1),
            metadata=region.get("metadata", {}),
        )
        classification = self.process_classify_block(parsed)
        needs = self.process_needs_reinfer(parsed)
        reason = (
            f"classificação '{classification}' requer re-inferência"
            if needs
            else "região já processável"
        )
        return {"needs_reinfer": needs, "reason": reason}
