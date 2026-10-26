from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from acessilia_sdk.toolbox.clients import ToolboxArtifactClient, ToolboxStructureClient

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import LOG_ARTIFACT_UPLOAD_DEGRADED
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxCapabilityClient,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    make_toolbox_client,
)

if TYPE_CHECKING:
    from docstruct.policy import FusionPolicy


def _one_artifact_endpoint(*clients: ToolboxCapabilityClient | None) -> bool:
    """IDs are reusable only within one configured Toolbox deployment.

    Multiple URLs represent independent deployments (ADR-0006), so the source
    must accompany extraction instead of relying on an upload client choosing
    the same deployment. A single URL may address a shared-storage balancer.
    """
    urls: set[str] = set()
    for client in clients:
        if client is None:
            continue
        endpoints = getattr(client, "endpoints", ())
        client_urls = {endpoint.base_url for endpoint in endpoints}
        base_url = getattr(client, "base_url", None)
        if not client_urls and isinstance(base_url, str):
            client_urls.add(base_url.rstrip("/"))
        urls.update(client_urls)
    return len(urls) <= 1


@dataclass(frozen=True)
class ToolboxExtraction:
    """Resultado da extração via Toolbox.

    Carrega o JSON completo da resposta da Toolbox, de onde o builder lê
    elements e pages diretamente.
    """

    document: dict[str, Any]
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    version: str
    configuration: dict[str, Any]
    artifact_id: str | None = None
    cache_key: str | None = None


class ToolboxManifestExtractor:
    """Extrator que consome a Acessilia Toolbox via REST.

    É o único extrator de manifesto do core: a extração roda na Toolbox
    (docs/adr/0003).
    O método extract() é síncrono para compatibilidade com
    InformationalStructuralAgent.process() que roda dentro de asyncio.to_thread.
    """

    def __init__(
        self,
        *,
        client: ToolboxStructureClient | None = None,
        artifact_client: ToolboxArtifactClient | None = None,
        enable_ocr: bool = True,
        use_artifact_store: bool | None = None,
        use_remote_cache: bool | None = None,
        fusion_policy: FusionPolicy | None = None,
    ) -> None:
        # Clients passed in are reused and left open. Otherwise each extraction
        # builds its own and closes them: extract() runs every document on a
        # fresh event loop, and an HTTP connection must not outlive its loop.
        self._client = client
        self._artifact_client = artifact_client
        self.enable_ocr = enable_ocr
        # Policy for FUSION_MODE=dual; None keeps the fusion stack's default.
        self.fusion_policy = fusion_policy
        self.use_artifact_store = (
            use_artifact_store
            if use_artifact_store is not None
            else settings.toolbox_use_artifact_store
        )
        self.use_remote_cache = (
            use_remote_cache
            if use_remote_cache is not None
            else settings.toolbox_use_remote_cache
        )

    def extract(
        self, source_path: Path, *, dual_fusion: bool = True
    ) -> ToolboxExtraction:
        """Extrai a estrutura de um documento usando a Toolbox (síncrono).

        Executa chamadas HTTP assíncronas via asyncio.run() em thread separada,
        compatível com o fluxo existente que chama extract() dentro de
        asyncio.to_thread(). With ``dual_fusion=False`` the secondary provider
        is not called even in FUSION_MODE=dual (a presentation).
        """
        return asyncio.run(self._extract_async(source_path, dual_fusion=dual_fusion))

    async def _extract_async(
        self, source_path: Path, *, dual_fusion: bool = True
    ) -> ToolboxExtraction:
        structure = self._client or make_toolbox_client(ToolboxStructureClient)
        artifacts = self._artifact_client
        if (
            artifacts is None
            and self.use_artifact_store
            and _one_artifact_endpoint(structure)
        ):
            artifacts = make_toolbox_client(ToolboxArtifactClient)
        try:
            return await self._extract_with(
                structure, artifacts, source_path, dual_fusion=dual_fusion
            )
        finally:
            if self._client is None:
                await structure.close()
            if self._artifact_client is None and artifacts is not None:
                await artifacts.close()

    async def _extract_with(
        self,
        structure: ToolboxStructureClient,
        artifacts: ToolboxArtifactClient | None,
        source_path: Path,
        *,
        dual_fusion: bool = True,
    ) -> ToolboxExtraction:
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Documento não encontrado: {source_path}")

        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()

        artifact_id: str | None = None
        upload_error: str | None = None
        use_artifact_store = (
            self.use_artifact_store
            and artifacts is not None
            and _one_artifact_endpoint(structure, artifacts)
        )
        if use_artifact_store and artifacts is not None:
            try:
                artifact_id = await artifacts.upload(source_path)
            except (ToolboxTimeout, ToolboxProviderUnavailable) as exc:
                upload_error = type(exc).__name__
                use_artifact_store = False
                logger.warning(t(LOG_ARTIFACT_UPLOAD_DEGRADED).format(error=upload_error))
            else:
                logger.info(
                    "Toolbox: artifact {} stored ({})", artifact_id, source_path.name
                )

        result = await structure.extract_structure(
            file_path=None if artifact_id else source_path,
            artifact_id=artifact_id,
            language="pt-BR",
            use_remote_cache=self.use_remote_cache,
        )
        logger.info(
            "Toolbox: structure extracted ({} ms, provider={})",
            result.get("provenance", {}).get("duration_ms", "?"),
            result.get("provider", "?"),
        )
        if settings.fusion_mode == "dual" and dual_fusion:
            secondary_provider = settings.fusion_secondary_provider
            if secondary_provider == structure.provider:
                logger.warning(
                    "Fusão dual ignorada: provider primário e secundário são ambos {}",
                    secondary_provider,
                )
            else:
                from backend.pipeline.fusion import (
                    apply_page_routes,
                    fuse_extraction_payloads,
                )

                secondary_client = make_toolbox_client(
                    ToolboxStructureClient, provider=secondary_provider
                )
                try:
                    secondary_artifact_id = (
                        artifact_id
                        if _one_artifact_endpoint(
                            structure, artifacts, secondary_client
                        )
                        else None
                    )
                    secondary_result = await secondary_client.extract_structure(
                        file_path=None if secondary_artifact_id else source_path,
                        artifact_id=secondary_artifact_id,
                        language="pt-BR",
                        use_remote_cache=self.use_remote_cache,
                    )
                except ToolboxError as exc:
                    logger.warning(
                        "Fusão dual sem evidência: provider {} falhou ({})",
                        secondary_provider,
                        type(exc).__name__,
                    )
                else:
                    fusion = fuse_extraction_payloads(
                        result,
                        secondary_result,
                        primary_provider=structure.provider,
                        secondary_provider=secondary_provider,
                        policy=self.fusion_policy,
                    )
                    replaced: dict[int, list[dict[str, Any]]] = {}
                    if settings.fusion_apply_page_routes:
                        result, replaced = apply_page_routes(
                            result,
                            secondary_result,
                            fusion["fusion_evidence"]["pages"],
                            secondary_provider=secondary_provider,
                        )
                    result = {
                        **result,
                        "fusion_stats": fusion["fusion_stats"],
                        "fusion_evidence": fusion["fusion_evidence"],
                        "secondary_extraction": _persist_secondary_extraction(
                            secondary_result, secondary_provider, replaced
                        ),
                    }
                finally:
                    await secondary_client.close()

        duration_ms = round((perf_counter() - started_clock) * 1000)
        completed_at = datetime.now(timezone.utc)

        provenance = result.get("provenance", {})
        cache_key = provenance.get("cache_key")

        return ToolboxExtraction(
            document=result,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            version=provenance.get("provider_version", "unknown"),
            configuration={
                "ocr": self.enable_ocr,
                "table_structure": True,
                "remote_services": True,
                "toolbox_base_url": structure.base_url,
                "toolbox_provider": structure.provider,
                "use_artifact_store": use_artifact_store,
                **({"artifact_upload_error": upload_error} if upload_error else {}),
                "use_remote_cache": self.use_remote_cache,
                "artifact_id": artifact_id,
                "cache_key": cache_key,
            },
            artifact_id=artifact_id,
            cache_key=cache_key,
        )


def _persist_secondary_extraction(
    payload: dict[str, Any],
    provider: str,
    replaced_primary: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    """Keep the secondary provider's extraction for the planning methods.

    The fusion evidence only carries per-page statistics, but the methods that
    resolve the obligations it raises (table source, skeleton order, page
    routing) decide between the two providers' blocks. The file is named by its
    content hash and the hash is recorded, so a reader can tell it was not
    replaced afterwards.

    A write failure does not fail the extraction: the manifest goes without the
    artifact and those methods report it as unavailable.
    """
    record: dict[str, Any] = {"provider": provider, "document": payload}
    if replaced_primary:
        # The primary provider's elements of the pages taken from this provider,
        # so the VLM judge can still compare both transcriptions of those pages.
        record["replaced_primary_pages"] = {
            str(page): elements for page, elements in replaced_primary.items()
        }
    content = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    path = settings.data_dir / "artifacts" / "fusion" / f"secondary-{digest[:16]}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError as exc:
        logger.warning(
            "Extração secundária de {} não foi gravada ({}): {}",
            provider,
            type(exc).__name__,
            exc,
        )
        return {}
    return {"provider": provider, "path": str(path), "sha256": digest}
