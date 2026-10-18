"""Client for ``document.export.pdf_ua``: a Pandoc AST rendered as PDF/UA.

The Toolbox renders the PDF with Pandoc and TeX Live pinned in its own image.
The PDF is not embedded in the response: the Toolbox stores it as an artifact
and returns its ``artifact_id``, which is downloaded and verified from the
endpoint that served the call. The Toolbox execution cache covers the AST, the
language and the toolchain versions, so re-exporting the same document reuses
the PDF without running LaTeX.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.artifacts import ArtifactRef, download_artifact
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

CAPABILITY = "document.export.pdf_ua"
PDF_MEDIA_TYPE = "application/pdf"
#: The upload filename is part of the Toolbox cache key: a fixed name keeps the
#: same document, exported by different jobs, hitting the cache.
UPLOAD_FILENAME = "document.ast.json"
#: The only AST keys pandoc reads.
PANDOC_AST_KEYS = ("pandoc-api-version", "meta", "blocks")


def pandoc_payload(ast: dict[str, Any]) -> bytes:
    """Serialize only the part of the AST pandoc reads, deterministically.

    Extra keys (such as a ``source_document`` with a random id) are ignored by
    pandoc but would change the upload hash on every run, and the Toolbox
    cache would never be reused.
    """
    trimmed = {key: ast[key] for key in PANDOC_AST_KEYS if key in ast}
    return json.dumps(trimmed, ensure_ascii=False, sort_keys=True).encode("utf-8")


class ToolboxPdfUaClient(ToolboxCapabilityClient):
    """PDF/UA export."""

    provider_key = "toolbox_pdf_ua_provider"

    async def export(
        self,
        ast: dict[str, Any],
        output_path: Path,
        *,
        lang: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """Render ``ast`` as PDF/UA and write the verified PDF to ``output_path``.

        ``ast`` is a Pandoc JSON AST, already without images (alt text only);
        ``lang`` is the BCP 47 tag written to the PDF metadata. Returns the
        response envelope; its ``document`` follows ``artifact/pdf-export@1``
        (``artifact_id``, size, toolchain versions) and its ``provenance``
        reports the cache hit and duration.
        """
        http, result = await self._execute_on(
            CAPABILITY,
            upload=(UPLOAD_FILENAME, pandoc_payload(ast), "application/json"),
            parameters={"lang": lang},
            no_cache=use_remote_cache is False,
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
        await download_artifact(
            http, ArtifactRef.parse(artifact_id), output_path, magic=b"%PDF-"
        )
        return result


__all__ = ["CAPABILITY", "PANDOC_AST_KEYS", "ToolboxPdfUaClient", "pandoc_payload"]
