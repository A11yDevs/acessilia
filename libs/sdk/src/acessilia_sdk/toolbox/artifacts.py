"""Content-addressed artifacts stored in the Toolbox and their verified download.

Capabilities whose output is a file (e.g. ``document.export.pdf_ua``) return an
``artifact_id`` instead of the bytes. The id is the SHA-256 of the content, so a
download can be checked before it reaches the caller.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from acessilia_sdk.toolbox.errors import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)
from acessilia_sdk.toolbox.transport import raise_for_error

#: Same pattern as ``artifact_id`` in the Toolbox artifact schemas.
ARTIFACT_ID_RE = re.compile(r"^(?:sha256:)?(?P<digest>[0-9a-f]{64})$")


@dataclass(frozen=True)
class ArtifactRef:
    """An artifact id with the SHA-256 digest it promises.

    Provisional: the Toolbox owns the artifact reference contract. Once it
    publishes ``artifact-ref@1``, this class is replaced by the model generated
    from that schema.
    """

    artifact_id: str
    digest: str

    @classmethod
    def parse(cls, artifact_id: str) -> ArtifactRef:
        match = ARTIFACT_ID_RE.match(artifact_id or "")
        if match is None:
            raise ToolboxContractViolation(
                f"Malformed Toolbox artifact_id {artifact_id!r}"
            )
        return cls(artifact_id, match["digest"])


async def download_artifact(
    http: httpx.AsyncClient,
    ref: ArtifactRef,
    destination: Path,
    *,
    magic: bytes | None = None,
) -> None:
    """``GET /v1/artifacts/{id}``, verify it and write it atomically to ``destination``.

    The content must hash to ``ref.digest`` and, when ``magic`` is given, start
    with it. An interrupted or rejected download leaves no partial file behind.
    ``http`` must be the client of the endpoint that produced the artifact.
    """
    path = f"/v1/artifacts/{ref.artifact_id}"
    try:
        response = await http.get(path)
    except httpx.TimeoutException as e:
        raise ToolboxTimeout(
            f"Timed out downloading artifact {ref.artifact_id}: {e}"
        ) from e
    except httpx.RequestError as e:
        raise ToolboxProviderUnavailable(
            f"Toolbox unavailable at {http.base_url}: {e}"
        ) from e
    raise_for_error(response, "artifact.retrieve")

    content = response.content
    if hashlib.sha256(content).hexdigest() != ref.digest:
        raise ToolboxContractViolation(
            f"Downloaded content does not match artifact_id {ref.artifact_id}"
        )
    if magic is not None and not content.startswith(magic):
        raise ToolboxContractViolation(
            f"Artifact {ref.artifact_id} does not start with {magic!r}"
        )

    partial = destination.with_name(f".{destination.name}.part")
    partial.write_bytes(content)
    os.replace(partial, destination)


__all__ = ["ARTIFACT_ID_RE", "ArtifactRef", "download_artifact"]
