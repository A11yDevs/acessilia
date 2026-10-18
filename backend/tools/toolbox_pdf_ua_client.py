"""Specialized client for the Toolbox document.export.pdf_ua capability.

Sends the Pandoc AST (JSON) to the Toolbox, which renders PDF/UA with Pandoc
and TeX Live pinned in its own image. The PDF is not embedded in the response:
the Toolbox writes it to the artifact store (MinIO) and returns only the
``artifact_id``, which this client downloads through ``GET /v1/artifacts/{id}``.

The Toolbox execution cache (Valkey) covers the AST, the language and the
toolchain versions; re-exporting the same document reuses the PDF without
running LaTeX.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxCapabilityClient,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    _raise_for_error,
    run_sync,
)

CAPABILITY = "document.export.pdf_ua"
PDF_MEDIA_TYPE = "application/pdf"
# The upload filename is part of the Toolbox cache key: a fixed name keeps the
# same document, exported by different jobs, hitting the cache.
UPLOAD_FILENAME = "document.ast.json"
# The only AST keys pandoc reads.
PANDOC_AST_KEYS = ("pandoc-api-version", "meta", "blocks")
# Same pattern as ``artifact_id`` in the Toolbox schema artifact/pdf-export@1.
ARTIFACT_ID_RE = re.compile(r"^(?:sha256:)?(?P<digest>[0-9a-f]{64})$")


def pandoc_payload(ast: dict[str, Any]) -> bytes:
    """Serializes only the part of the AST pandoc reads, deterministically.

    ``build_pandoc_ast`` attaches ``source_document`` (the canonical document,
    with a random ``id``). Pandoc ignores it, but it would change the upload
    hash on every run and the Toolbox cache would never be reused.
    """
    trimmed = {key: ast[key] for key in PANDOC_AST_KEYS if key in ast}
    return json.dumps(trimmed, ensure_ascii=False, sort_keys=True).encode("utf-8")


class ToolboxPdfUaClient(ToolboxCapabilityClient):
    """Client for PDF/UA export through the Acessilia Toolbox."""

    provider_key = "toolbox_pdf_ua_provider"

    def __init__(self, *args: Any, timeout_seconds: int | None = None, **kwargs: Any):
        # The shared Toolbox timeout (default one hour) would stall the export
        # long before the local fallback runs if the renderer hangs.
        super().__init__(
            *args,
            timeout_seconds=timeout_seconds or settings.toolbox_pdf_ua_timeout_seconds,
            **kwargs,
        )

    async def export(
        self,
        ast: dict[str, Any],
        output_path: Path,
        *,
        lang: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """Renders ``ast`` as PDF/UA on the Toolbox and writes the PDF to ``output_path``.

        Args:
            ast: Pandoc JSON AST, already without images (alt text only).
            output_path: Destination of the downloaded PDF.
            lang: BCP 47 tag written to the PDF metadata.
            use_remote_cache: When False, forces a fresh render on the Toolbox.

        Returns:
            The response ``document`` (schema artifact/pdf-export@1), with the
            ``artifact_id``, the size and the toolchain versions.
        """
        use_cache = (
            use_remote_cache
            if use_remote_cache is not None
            else settings.toolbox_use_remote_cache
        )
        result = await self._execute(
            CAPABILITY,
            upload=(UPLOAD_FILENAME, pandoc_payload(ast), "application/json"),
            parameters={"lang": lang},
            no_cache=not use_cache,
        )

        document = result.get("document")
        if not isinstance(document, dict):
            raise ToolboxContractViolation(
                f"{CAPABILITY} response has no 'document' field"
            )
        artifact_id = document.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ToolboxContractViolation(
                f"{CAPABILITY} response has no PDF artifact_id"
            )
        if document.get("media_type") != PDF_MEDIA_TYPE:
            raise ToolboxContractViolation(
                f"{CAPABILITY} returned {document.get('media_type')!r}, expected PDF"
            )

        await self._download(artifact_id, output_path)

        provenance = result.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        logger.info(
            "Toolbox: {} finished ({} bytes, cache_hit={}, {} ms)",
            CAPABILITY,
            document.get("size_bytes", "?"),
            provenance.get("cache_hit", False),
            provenance.get("duration_ms", "?"),
        )
        return document

    async def _download(self, artifact_id: str, output_path: Path) -> None:
        """Downloads the PDF and checks that its bytes hash to ``artifact_id``.

        The id is the SHA-256 of the content, so the check catches a truncated
        download or a corrupted object before it reaches the user.
        """
        match = ARTIFACT_ID_RE.match(artifact_id)
        if match is None:
            raise ToolboxContractViolation(
                f"{CAPABILITY} returned a malformed artifact_id {artifact_id!r}"
            )
        try:
            response = await self._client.get(f"/v1/artifacts/{artifact_id}")
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timed out downloading PDF {artifact_id} from the Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox unavailable at {self.base_url}: {e}"
            ) from e
        _raise_for_error(response, "artifact.retrieve")

        content = response.content
        if hashlib.sha256(content).hexdigest() != match["digest"]:
            raise ToolboxContractViolation(
                f"Downloaded PDF does not match artifact_id {artifact_id}"
            )
        if not content.startswith(b"%PDF-"):
            raise ToolboxContractViolation(f"Artifact {artifact_id} is not a PDF")

        # Atomic write: an interrupted download leaves no partial PDF behind.
        partial = output_path.with_name(f".{output_path.name}.part")
        partial.write_bytes(content)
        os.replace(partial, output_path)


def toolbox_export_pdf_ua(
    ast: dict[str, Any], output_path: Path, *, lang: str = "pt-BR"
) -> dict[str, Any]:
    """Synchronous form of :meth:`ToolboxPdfUaClient.export` for the exporter.

    The client is created and closed inside the coroutine: ``run_sync`` may run
    it on a fresh event loop, and the HTTP connection must not outlive it.
    """

    async def _export() -> dict[str, Any]:
        client = ToolboxPdfUaClient()
        try:
            return await client.export(ast, output_path, lang=lang)
        finally:
            await client.close()

    return run_sync(_export())


__all__ = ["ToolboxPdfUaClient", "toolbox_export_pdf_ua"]
