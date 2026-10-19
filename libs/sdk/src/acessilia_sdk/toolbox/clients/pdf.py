"""Client for ``pdf.split`` and ``pdf.render``."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from acessilia_sdk.toolbox.artifacts import ArtifactRef, read_artifact
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

SPLIT_CAPABILITY = "pdf.split"
RENDER_CAPABILITY = "pdf.render"


#: Origin of the coordinates of a requested ``clip``.
ClipOrigin = Literal["TOPLEFT", "BOTTOMLEFT"]

_CLIP_KEYS = ("left", "top", "right", "bottom")


@dataclass(frozen=True)
class RenderedPage:
    """A page rendered by ``pdf.render@2``: the PNG and what was applied.

    ``clip`` is the region rendered, ``(left, top, right, bottom)`` in page
    units with a top-left origin, already intersected with the page.
    ``document`` is the whole ``artifact/image@2`` result: ``scale``, ``dpi``,
    ``width_px``/``height_px``, ``page_width``/``page_height`` (page units)
    and ``page_count`` among others.
    """

    image: bytes
    clip: tuple[float, float, float, float]
    document: dict[str, Any]

    @property
    def page_count(self) -> int:
        return self.document["page_count"]


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _checked_render(document: Any, page_number: int) -> tuple[float, float, float, float]:
    """Validate the parts of an ``image@2`` result the caller relies on; return its clip."""
    context = f"{RENDER_CAPABILITY}@2"
    if not isinstance(document, dict):
        raise ToolboxContractViolation(f"{context} response has no document")
    if not document.get("artifact_id"):
        raise ToolboxContractViolation(f"{context} response has no image artifact")
    if document.get("media_type") != "image/png":
        raise ToolboxContractViolation(
            f"{context} returned {document.get('media_type')!r}, not image/png"
        )
    if document.get("page_number") != page_number:
        raise ToolboxContractViolation(
            f"{context} rendered page {document.get('page_number')!r}, not {page_number}"
        )
    page_count = document.get("page_count")
    if type(page_count) is not int or page_count < 1:
        raise ToolboxContractViolation(f"{context} response has no valid page_count")
    box = document.get("clip")
    # image@2 reports the clip with exactly these keys, always with a top-left
    # origin; anything else (an origin field, a missing side) is not v2.
    if (
        not isinstance(box, dict)
        or set(box) != set(_CLIP_KEYS)
        or not all(_number(box[key]) for key in _CLIP_KEYS)
    ):
        raise ToolboxContractViolation(
            f"{context} response does not report the applied clip"
        )
    left, top, right, bottom = (float(box[key]) for key in _CLIP_KEYS)
    return left, top, right, bottom


class ToolboxPdfClient(ToolboxCapabilityClient):
    """Split a PDF into pages and render a page as PNG."""

    provider_key = "toolbox_pdf_provider"

    async def split(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/pdf.split:execute``.

        Returns the response envelope; its ``document`` holds ``page_count``,
        ``pages`` (per-page metadata) and ``source_filename``.
        """
        return await self._execute(
            SPLIT_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            no_cache=use_remote_cache is False,
        )

    async def render(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        page_number: int = 1,
        dpi: int = 150,
        max_side: int | None = None,
        clip: tuple[float, float, float, float] | None = None,
        clip_origin: ClipOrigin = "TOPLEFT",
        use_remote_cache: bool | None = None,
    ) -> RenderedPage:
        """Render one page of a PDF, PNG or JPEG on the Toolbox (``pdf.render@2``).

        ``clip`` is ``(left, top, right, bottom)`` in page units with
        ``clip_origin``; the Toolbox converts, normalizes and intersects it.
        ``max_side`` bounds the longest side in pixels; with ``dpi``, the
        smaller scale wins. The PNG is stored on the Toolbox and fetched, and
        verified, from the endpoint that rendered it.
        """
        parameters: dict[str, Any] = {"page_number": page_number, "dpi": dpi}
        if max_side is not None:
            parameters["max_side"] = max_side
        if clip is not None:
            left, top, right, bottom = clip
            parameters["clip"] = {
                "left": left, "top": top, "right": right, "bottom": bottom,
                "origin": clip_origin,
            }
        http, result = await self._execute_on(
            RENDER_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters=parameters,
            no_cache=use_remote_cache is False,
        )
        document = result.get("document")
        clip_applied = _checked_render(document, page_number)
        image = await read_artifact(
            http, ArtifactRef.parse(str(document["artifact_id"])), magic=b"\x89PNG"
        )
        if document.get("size_bytes") != len(image):
            raise ToolboxContractViolation(
                f"{RENDER_CAPABILITY}@2 reported {document.get('size_bytes')!r} bytes, "
                f"got {len(image)}"
            )
        return RenderedPage(image=image, clip=clip_applied, document=document)


__all__ = [
    "RENDER_CAPABILITY",
    "SPLIT_CAPABILITY",
    "ClipOrigin",
    "RenderedPage",
    "ToolboxPdfClient",
]
