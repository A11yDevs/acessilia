"""Client for the artifact store: ``POST /v1/artifacts`` and ``GET /v1/artifacts/{id}``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from acessilia_sdk.toolbox.artifacts import ArtifactRef, download_artifact, parse_reference
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation
from acessilia_sdk.toolbox.reference import ArtifactReference
from acessilia_sdk.toolbox.transport import media_type_for

STORE_CAPABILITY = "artifact.store"
RETRIEVE_CAPABILITY = "artifact.retrieve"


class ToolboxArtifactClient(ToolboxCapabilityClient):
    """Store files in the Toolbox and fetch them back, verified."""

    async def upload(self, file_path: Path) -> str:
        """Store ``file_path`` and return its ``artifact_id``.

        The file is streamed from disk, reopened on each retry. Replicas behind
        one load balancer share the store, so the id is valid on all of them
        (docs/adr/0006). It reads the id only, so it works with a Toolbox that
        answers with ``artifact/reference@1`` and with one from before it.
        """
        data = await self._store(file_path)
        artifact_id = (
            (data.get("artifact_id") or data.get("id")) if isinstance(data, dict) else None
        )
        if not artifact_id:
            raise ToolboxContractViolation(f"{STORE_CAPABILITY} response has no artifact_id")
        return str(artifact_id)

    async def upload_reference(self, file_path: Path) -> ArtifactReference:
        """Store ``file_path`` and return its ``artifact/reference@1`` (ADR-0015).

        Needs a Toolbox whose ``POST /v1/artifacts`` answers with the published
        reference (acessilia-toolbox#151). Against an earlier Toolbox, which
        answers with its stored record, it raises :class:`ToolboxContractViolation`
        instead of inventing ``digest`` or ``store``; :meth:`upload` still works
        there.
        """
        data = await self._store(file_path)
        if isinstance(data, dict) and "digest" not in data and "artifact_id" in data:
            raise ToolboxContractViolation(
                f"{STORE_CAPABILITY} answered without a digest: this Toolbox predates "
                "artifact/reference@1 on POST /v1/artifacts; use upload() for the id"
            )
        return parse_reference(data)

    async def _store(self, file_path: Path) -> Any:
        """``POST /v1/artifacts`` with ``file_path``; the decoded JSON body."""

        @contextmanager
        def files() -> Iterator[dict[str, Any]]:
            with open(file_path, "rb") as stream:
                yield {"file": (file_path.name, stream, media_type_for(file_path))}

        _, response = await self._request_on(
            "POST", "/v1/artifacts", capability_id=STORE_CAPABILITY, files_factory=files
        )
        try:
            return response.json()
        except ValueError as e:
            raise ToolboxContractViolation(
                f"{STORE_CAPABILITY} response is not valid JSON"
            ) from e

    async def download(
        self, artifact_id: str, destination: Path, *, magic: bytes | None = None
    ) -> None:
        """Download ``artifact_id`` to ``destination``, checked against its digest.

        The body is streamed by :func:`~acessilia_sdk.toolbox.artifacts.download_artifact`
        from whichever endpoint answers.
        """
        ref = ArtifactRef.parse(artifact_id)

        async def call(http: httpx.AsyncClient) -> None:
            await download_artifact(http, ref, destination, magic=magic)

        await self._rest_with_failover(
            RETRIEVE_CAPABILITY, call, missing_artifact_failover=True
        )


__all__ = ["RETRIEVE_CAPABILITY", "STORE_CAPABILITY", "ToolboxArtifactClient"]
