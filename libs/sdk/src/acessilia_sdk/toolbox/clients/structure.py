"""Client for ``document.structure.extract``: the document structure from a provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.results.layout import ManifestResult, read_manifest

CAPABILITY = "document.structure.extract"


class ToolboxStructureClient(ToolboxCapabilityClient):
    """Structure extraction (Docling, MinerU, Nougat, TeleOCR…)."""

    provider_key = "toolbox_provider"
    timeout_key = "toolbox_structure_timeout_seconds"

    async def extract_structure(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/document.structure.extract:execute``.

        Takes a direct upload (``file_path``) or an artifact already stored in
        the Toolbox (``artifact_id``). Returns the response envelope; its
        ``document`` follows ``structured-document@1``.
        """
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            no_cache=use_remote_cache is False,
        )

    async def extract_structure_result(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> ManifestResult:
        """Typed published result, preserving the existing raw method."""
        result = await self.extract_structure(
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            use_remote_cache=use_remote_cache,
        )
        return read_manifest(result.get("document"))


__all__ = ["CAPABILITY", "ToolboxStructureClient"]
