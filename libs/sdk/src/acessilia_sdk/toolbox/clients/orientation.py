"""Client for ``image.page.orient``: the correction angle of a page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

CAPABILITY = "image.page.orient"


class ToolboxOrientationClient(ToolboxCapabilityClient):
    """Page orientation detection (0/90/180/270)."""

    provider_key = "toolbox_orientation_provider"

    async def detect(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        return_image: bool = False,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/image.page.orient:execute``.

        ``return_image`` includes the rotated image in the result. Returns the
        response envelope; its ``document`` holds ``angle``, ``confidence``,
        ``stage`` and the original and oriented dimensions.
        """
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={"return_image": return_image},
            no_cache=use_remote_cache is False,
        )


__all__ = ["CAPABILITY", "ToolboxOrientationClient"]
