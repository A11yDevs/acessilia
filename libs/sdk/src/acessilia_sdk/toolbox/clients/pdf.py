"""Client for ``pdf.split`` and ``pdf.render``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from acessilia_sdk.toolbox.artifacts import ArtifactRef, read_artifact
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

SPLIT_CAPABILITY = "pdf.split"
RENDER_CAPABILITY = "pdf.render"


@dataclass(frozen=True)
class RenderedPage:
    """A page rendered by ``pdf.render@2``: the PNG and what was applied.

    ``document`` follows ``artifact/image@2``: ``clip`` (the region rendered,
    top-left origin, intersected with the page), ``scale``, ``dpi``,
    ``width_px``/``height_px``, ``page_width``/``page_height`` (page units)
    and ``page_count``.
    """

    image: bytes
    document: dict[str, Any]

    @property
    def clip(self) -> tuple[float, float, float, float]:
        box = self.document["clip"]
        return (box["left"], box["top"], box["right"], box["bottom"])


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
        clip_origin: Literal["TOPLEFT", "BOTTOMLEFT"] = "TOPLEFT",
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
        if not isinstance(document, dict) or document.get("media_type") != "image/png":
            raise ToolboxContractViolation(
                f"{RENDER_CAPABILITY} response has no PNG artifact"
            )
        if not isinstance(document.get("clip"), dict):
            raise ToolboxContractViolation(
                f"{RENDER_CAPABILITY} response does not report the applied clip"
            )
        image = await read_artifact(
            http, ArtifactRef.parse(str(document.get("artifact_id", ""))), magic=b"\x89PNG"
        )
        return RenderedPage(image=image, document=document)


__all__ = ["RENDER_CAPABILITY", "SPLIT_CAPABILITY", "RenderedPage", "ToolboxPdfClient"]
