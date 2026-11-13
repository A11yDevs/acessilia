"""The secondary provider's extraction in ``FUSION_MODE=dual``, and pairing with it.

The structure extractor keeps the secondary provider's extraction as a manifest
artifact. The handlers that compare the providers (``table-smart-fusion``,
``agreement-rule``, ``skeleton-order``) and the page judge read it through
``_secondary_or_failure``: a missing, replaced or unreadable artifact, or a
provider pair other than the calibrated one, fails the method explicitly
instead of applying a preference nobody measured. ``_pair_block`` pairs a
manifest element with a secondary block by position or text, and
``_page_markdown`` writes a page's text with the markers the page router
compares; ``agreement-rule`` and the judge both use it. Moved verbatim from the
PDDL orchestrator (#402, phase 3, step 6).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docstruct.fusion.similarity import ordered_box, pair_block

from backend.core.execution.models import MethodResult
from backend.core.manifest.builder import (
    SECONDARY_EXTRACTION_KIND,
)
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
    is_bottom_left,
)
from backend.i18n import t
from backend.core.pipeline.handlers.messages import (
    MSG_PROVIDER_PAIR_UNCALIBRATED,
    MSG_SECONDARY_CHANGED,
    MSG_SECONDARY_MISSING,
    MSG_SECONDARY_UNAVAILABLE,
    MSG_SECONDARY_UNREADABLE,
)
from backend.core.pipeline.elements import (
    _element_bbox,
)
from backend.tools.logger import logger


_CALIBRATED_PAIR = ("docling", "mineru")


#: Minimum intersection over union to pair two blocks by position.
_MIN_BLOCK_IOU = 0.3


#: Minimum text similarity to pair two blocks that could not be paired by position.
_MIN_BLOCK_TEXT_RATIO = 0.8


_Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class _SecondaryExtraction:
    provider: str
    #: page number -> raw elements of the secondary provider, in reading order.
    pages: dict[int, list[dict[str, Any]]]
    sizes: dict[int, tuple[float, float]]
    #: page number -> primary elements of a page the manifest took from the
    #: secondary provider (fusion.apply_page_routes), in reading order.
    replaced_primary: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def bbox(self, element: dict[str, Any]) -> _Box | None:
        """Normalized box of a raw Toolbox element (same frame as _element_bbox)."""
        for item in element.get("provenance") or []:
            if not isinstance(item, dict) or not item.get("bbox"):
                continue
            box = item["bbox"]
            page = _page_number(item.get("page_number", element.get("page_number")))
            width, height = self.sizes.get(page, (0.0, 0.0)) if page else (0.0, 0.0)
            if not width or not height:
                return None
            try:
                left, right = float(box["left"]), float(box["right"])
                top, bottom = float(box["top"]), float(box["bottom"])
            except (KeyError, TypeError, ValueError):
                return None
            if is_bottom_left(box.get("coord_origin"), top, bottom):
                top, bottom = height - top, height - bottom
            return ordered_box(
                left / width, top / height, right / width, bottom / height
            )
        return None


def _page_number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_secondary_extraction(
    manifest: ProcessingManifest,
) -> tuple[_SecondaryExtraction | None, str]:
    """The secondary provider's extraction, if recorded and unchanged.

    When it cannot be used, the second item says why (missing, replaced or
    unreadable), so the method result can tell those cases apart.
    """
    import json

    artifact = next(
        (a for a in manifest.artifacts if a.kind == SECONDARY_EXTRACTION_KIND), None
    )
    if artifact is None:
        return None, t(MSG_SECONDARY_MISSING)
    try:
        raw = Path(artifact.path).read_bytes()
    except OSError:
        return None, t(MSG_SECONDARY_UNAVAILABLE).format(path=artifact.path)
    if artifact.sha256 and hashlib.sha256(raw).hexdigest() != artifact.sha256:
        logger.warning(
            "Secondary extraction {} does not match the recorded sha256",
            artifact.path,
        )
        return None, t(MSG_SECONDARY_CHANGED).format(path=artifact.path)
    unreadable = t(MSG_SECONDARY_UNREADABLE).format(path=artifact.path)
    try:
        data = json.loads(raw)
    except ValueError:
        return None, unreadable
    payload = data.get("document") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None, unreadable
    document = payload.get("document", payload)
    sizes: dict[int, tuple[float, float]] = {}
    for page in document.get("pages") or []:
        try:
            sizes[int(page["page_number"])] = (
                float(page.get("width") or 0),
                float(page.get("height") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    pages: dict[int, list[dict[str, Any]]] = {}
    for element in sorted(
        (e for e in document.get("elements") or [] if isinstance(e, dict)),
        key=lambda e: e.get("reading_order") or 0,
    ):
        page = _page_number(element.get("page_number"))
        if page is not None:
            pages.setdefault(page, []).append(element)
    replaced: dict[int, list[dict[str, Any]]] = {}
    for key, rows in (data.get("replaced_primary_pages") or {}).items():
        page = _page_number(key)
        if page is not None and isinstance(rows, list):
            replaced[page] = sorted(
                (row for row in rows if isinstance(row, dict)),
                key=lambda row: row.get("reading_order") or 0,
            )
    return (
        _SecondaryExtraction(str(data.get("provider") or ""), pages, sizes, replaced),
        "",
    )


def _provider_pair_problem(
    manifest: ProcessingManifest, secondary: _SecondaryExtraction
) -> str | None:
    primary = str((manifest.extractor.configuration or {}).get("toolbox_provider") or "")
    if (primary, secondary.provider) == _CALIBRATED_PAIR:
        return None
    return t(MSG_PROVIDER_PAIR_UNCALIBRATED).format(
        expected="+".join(_CALIBRATED_PAIR),
        primary=primary or "?",
        secondary=secondary.provider or "?",
    )


def _secondary_or_failure(
    manifest: ProcessingManifest,
) -> tuple[_SecondaryExtraction | None, MethodResult | None]:
    secondary, problem = _load_secondary_extraction(manifest)
    if secondary is None:
        return None, MethodResult(success=False, validated=False, message=problem)
    problem = _provider_pair_problem(manifest, secondary)
    if problem:
        return None, MethodResult(success=False, validated=False, message=problem)
    return secondary, None


def _pair_block(
    element: ManifestElement,
    manifest: ProcessingManifest,
    candidates: list[dict[str, Any]],
    secondary: _SecondaryExtraction,
    used: set[int],
) -> int | None:
    """Index in ``candidates`` of the block that matches ``element`` (``pair_block``)."""
    box = _element_bbox(element, manifest)
    boxes = (
        []
        if box is None
        else [
            None if index in used else secondary.bbox(candidate)
            for index, candidate in enumerate(candidates)
        ]
    )
    return pair_block(
        box,
        element.text or "",
        boxes,
        [candidate.get("text") for candidate in candidates],
        used,
        min_iou=_MIN_BLOCK_IOU,
        min_text_ratio=_MIN_BLOCK_TEXT_RATIO,
    )


def _page_markdown(items: Iterable[tuple[str, str | None]]) -> str:
    """Page text with the markers the page router looks for."""
    parts = []
    for kind, text in items:
        text = (text or "").strip()
        if kind == "table":
            parts.append(f"<table>{text}</table>")
        elif kind == "formula":
            parts.append(f"$${text}$$")
        elif text:
            parts.append(text)
    return "\n\n".join(parts)
