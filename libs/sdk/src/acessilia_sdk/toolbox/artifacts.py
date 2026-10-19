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

    The body is streamed to a hidden ``.part`` file next to ``destination``
    and hashed on the way, so large artifacts are not held in memory. It must
    hash to ``ref.digest`` and, when ``magic`` is given, start with it. The file
    is synced to disk before it replaces ``destination``; a failed or rejected
    download leaves no partial file behind. ``http`` must be the client of the
    endpoint that produced the artifact.

    Toolbox failures raise :class:`ToolboxError` subclasses. Local file system
    errors (for instance a missing destination directory) are the caller's
    and propagate as ``OSError``.
    """
    partial = destination.with_name(f".{destination.name}.part")
    try:
        digest, head = await _stream_to(http, ref, partial, len(magic or b""))
        if digest != ref.digest:
            raise ToolboxContractViolation(
                f"Downloaded content does not match artifact_id {ref.artifact_id}"
            )
        if magic is not None and not head.startswith(magic):
            raise ToolboxContractViolation(
                f"Artifact {ref.artifact_id} does not start with {magic!r}"
            )
        os.replace(partial, destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    _sync_directory(destination.parent)


async def _stream_to(
    http: httpx.AsyncClient, ref: ArtifactRef, partial: Path, head_size: int
) -> tuple[str, bytes]:
    """Stream the artifact into ``partial``; return its hex digest and first bytes."""
    hasher = hashlib.sha256()
    head = b""
    try:
        async with http.stream("GET", f"/v1/artifacts/{ref.artifact_id}") as response:
            if not response.is_success:
                await response.aread()
                raise_for_error(response, "artifact.retrieve")
            with open(partial, "wb") as file:
                async for chunk in response.aiter_bytes():
                    hasher.update(chunk)
                    if len(head) < head_size:
                        head += chunk[: head_size - len(head)]
                    file.write(chunk)
                file.flush()
                os.fsync(file.fileno())
    except httpx.TimeoutException as e:
        raise ToolboxTimeout(
            f"Timed out downloading artifact {ref.artifact_id}: {e}"
        ) from e
    except httpx.RequestError as e:
        raise ToolboxProviderUnavailable(
            f"Toolbox unavailable at {http.base_url}: {e}"
        ) from e
    return hasher.hexdigest(), head


def _sync_directory(directory: Path) -> None:
    """Persist the rename itself; best effort where directories cannot be opened."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


__all__ = ["ARTIFACT_ID_RE", "ArtifactRef", "download_artifact"]
