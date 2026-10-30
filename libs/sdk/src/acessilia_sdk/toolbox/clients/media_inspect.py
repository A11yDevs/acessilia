"""Client for ``media.inspect``: deterministic facts about a document or image.

It reports dimensions, aspect ratio, page count, the nature of the artifact
(``standalone_image``, ``scanned_page``, ``paginated_document``, ``unknown``)
and whether it ``requires_visual_inspection``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

CAPABILITY = "media.inspect"


class ToolboxMediaInspectClient(ToolboxCapabilityClient):
    """Deterministic media inspection."""

    provider_key = "toolbox_media_inspect_provider"

    async def inspect(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/media.inspect:execute``.

        Returns the response's ``document`` (``artifact/media-inspection@1``):
        ``media_type``, ``is_image``, ``is_pdf``, ``page_count``,
        ``page_count_source`` (``pymupdf``, ``content_stream_scan``,
        ``pillow`` or ``None``), ``dimensions``, ``artifact_nature``, ``requires_visual_inspection``…
        """
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            no_cache=use_remote_cache is False,
        )
        document = result.get("document")
        if not isinstance(document, dict):
            raise ToolboxContractViolation(
                f"{CAPABILITY} response has no 'document' field"
            )
        return document


__all__ = ["CAPABILITY", "ToolboxMediaInspectClient"]
