"""Base client for the Toolbox exports that render a Pandoc AST into a file.

The Toolbox renders with the Pandoc pinned in its own image. The file is not
embedded in the response: the Toolbox stores it as an artifact and returns its
``artifact_id``, which is downloaded and verified from the endpoint that served
the call. The Toolbox execution cache covers the AST, the language and the
toolchain versions, so re-exporting the same document reuses the stored file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from acessilia_sdk.toolbox.artifacts import ArtifactRef, download_artifact
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

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


class PandocExportClient(ToolboxCapabilityClient):
    """Renders a Pandoc AST into one file format on the Toolbox."""

    capability: ClassVar[str]
    media_type: ClassVar[str]
    #: Short name of the format, used in error messages.
    format_name: ClassVar[str]
    #: Leading bytes every valid file starts with.
    magic: ClassVar[bytes]

    async def export(
        self,
        ast: dict[str, Any],
        output_path: Path,
        *,
        lang: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """Render ``ast`` and write the verified file to ``output_path``.

        ``ast`` is a Pandoc JSON AST, already without images (alt text only);
        ``lang`` is the BCP 47 tag written to the document metadata. Returns the
        response envelope; its ``document`` carries the ``artifact_id``, size and
        toolchain versions, and its ``provenance`` reports the cache hit and
        duration.
        """
        capability = self.capability
        http, result = await self._execute_on(
            capability,
            upload=(UPLOAD_FILENAME, pandoc_payload(ast), "application/json"),
            parameters={"lang": lang},
            no_cache=use_remote_cache is False,
        )
        document = result.get("document")
        if not isinstance(document, dict):
            raise ToolboxContractViolation(f"{capability} response has no 'document' field")
        artifact_id = document.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ToolboxContractViolation(
                f"{capability} response has no {self.format_name} artifact_id"
            )
        if document.get("media_type") != self.media_type:
            raise ToolboxContractViolation(
                f"{capability} returned {document.get('media_type')!r}, "
                f"expected {self.format_name}"
            )
        await download_artifact(
            http, ArtifactRef.parse(artifact_id), output_path, magic=self.magic
        )
        return result


__all__ = ["PANDOC_AST_KEYS", "UPLOAD_FILENAME", "PandocExportClient", "pandoc_payload"]
