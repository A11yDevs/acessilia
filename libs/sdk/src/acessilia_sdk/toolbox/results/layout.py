"""Readers for published layout variants and the shared structural document.

Only operational layout records are generated. Canonical document fields and
geometry are adapted to docstruct, while producer/process fields stay separate.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal

from docstruct.manifest import (
    BoundingBox,
    StructuredDocument,
    structured_document_from_payload,
)
from acessilia_sdk.toolbox.errors import ToolboxContractViolation
from acessilia_sdk.toolbox.results._layout_generated import (
    LayoutPages,
    MineruLayoutConfiguration,
    MANIFEST_RULE,
)
from acessilia_sdk.toolbox.results._model import decode

_DOCUMENT_FIELDS = {"title", "language", "pages", "elements"}


@dataclass(frozen=True)
class ManifestResult:
    document: StructuredDocument
    producer: dict[str, Any]
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """The original validated payload, preserving optional-field presence."""
        return copy.deepcopy(self.payload)


@dataclass(frozen=True)
class ClassifiedRegion:
    page_number: int
    type: str
    label: str
    bbox: BoundingBox
    confidence: float | None
    text: str | None


@dataclass(frozen=True)
class LayoutResult:
    variant: Literal["docling", "mineru"]
    regions: tuple[ClassifiedRegion, ...]
    compact: LayoutPages | None = None
    manifest: ManifestResult | None = None
    configuration: MineruLayoutConfiguration | None = None


def read_manifest(document: Any) -> ManifestResult:
    """Read structured-document@1, reusing docstruct instead of a new model.

    Wire validation enforces the pinned producer schema, including required
    process metadata. Date-time format annotations are not asserted (the same
    policy as JSON Schema's default validator without a FormatChecker).
    """
    try:
        checked = decode(document, MANIFEST_RULE, {}, "ProcessingManifest", strict=True)
        canonical = structured_document_from_payload(checked)
        return ManifestResult(
            canonical,
            {
                k: copy.deepcopy(v)
                for k, v in checked.items()
                if k not in _DOCUMENT_FIELDS
            },
            copy.deepcopy(checked),
        )
    except (ValueError, TypeError) as exc:
        raise ToolboxContractViolation(str(exc)) from exc


def read_layout(document: Any) -> LayoutResult:
    """Read the complete published layout union, including containing constraints.

    Compact coordinates have a top-left origin. MinerU classification metadata
    uses zero-based page indexes; canonical pages already use one-based numbers.
    MinerU supplies no classification confidence. Original metadata remains in
    ``configuration`` and ``manifest``. Classification boxes have no declared
    origin or guaranteed page units, so they stay UNKNOWN; use canonical element
    provenance before interpreting their geometry.
    """
    compact_error = None
    try:
        compact = LayoutPages.from_dict(document)
    except ValueError as exc:
        compact_error = exc
    else:
        regions = tuple(
            ClassifiedRegion(
                region.page_number,
                region.type,
                region.label,
                BoundingBox(*region.bbox, coord_origin="TOPLEFT"),
                region.confidence,
                region.text,
            )
            for page in compact.pages
            for region in page.regions
        )
        return LayoutResult("docling", regions, compact=compact)
    try:
        manifest = read_manifest(document)
        # Enforces the second allOf branch, in addition to ProcessingManifest.
        config = MineruLayoutConfiguration.from_dict(
            document["extractor"]["configuration"]
        )
        regions = tuple(
            ClassifiedRegion(
                region.page + 1,
                region.type,
                region.raw_label,
                BoundingBox(
                    *(region.bbox[key] for key in ("left", "top", "right", "bottom")),
                    coord_origin="UNKNOWN",
                ),
                None,
                region.text_preview,
            )
            for region in config.layout_regions
        )
        return LayoutResult("mineru", regions, manifest=manifest, configuration=config)
    except (KeyError, ValueError, TypeError, ToolboxContractViolation) as exc:
        raise ToolboxContractViolation(
            f"layout document matches neither published variant: {compact_error}; {exc}"
        ) from exc


__all__ = [
    "LayoutPages",
    "MineruLayoutConfiguration",
    "ManifestResult",
    "ClassifiedRegion",
    "LayoutResult",
    "read_layout",
    "read_manifest",
]
