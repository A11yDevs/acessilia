"""Client for the artifact store: ``POST /v1/artifacts`` and ``GET /v1/artifacts/{id}``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from acessilia_sdk.toolbox.artifacts import ArtifactRef, download_artifact
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation
from acessilia_sdk.toolbox.transport import media_type_for

STORE_CAPABILITY = "artifact.store"
RETRIEVE_CAPABILITY = "artifact.retrieve"


class ToolboxArtifactClient(ToolboxCapabilityClient):
    """Store files in the Toolbox and fetch them back, verified."""

    async def upload(self, file_path: Path) -> str:
        """Store ``file_path`` and return its ``artifact_id``.

        The file is streamed from disk, reopened on each retry. Replicas behind
        one load balancer share the store, so the id is valid on all of them
        (docs/adr/0006).
        """

        @contextmanager
        def files() -> Iterator[dict[str, Any]]:
            with open(file_path, "rb") as stream:
                yield {"file": (file_path.name, stream, media_type_for(file_path))}

        _, response = await self._request_on(
            "POST", "/v1/artifacts", capability_id=STORE_CAPABILITY, files_factory=files
        )
        try:
            data = response.json()
        except ValueError as e:
            raise ToolboxContractViolation(
                f"{STORE_CAPABILITY} response is not valid JSON"
            ) from e
        artifact_id = (
            (data.get("artifact_id") or data.get("id")) if isinstance(data, dict) else None
        )
        if not artifact_id:
            raise ToolboxContractViolation(f"{STORE_CAPABILITY} response has no artifact_id")
        return str(artifact_id)

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

        await self._rest_with_failover(RETRIEVE_CAPABILITY, call)


__all__ = ["RETRIEVE_CAPABILITY", "STORE_CAPABILITY", "ToolboxArtifactClient"]
