from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import (
    LOG_ARTIFACT_UPLOAD_DEGRADED,
    LOG_ARTIFACT_STORE_DIRECT_INPUT,
    LOG_DUAL_FUSION_SKIPPED_IDENTICAL_PROVIDERS,
    LOG_STRUCTURAL_PROVIDER_DEGRADED,
)
from backend.tools.logger import logger
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient, ToolboxStructureClient
from backend.tools.toolbox_client import (
    ToolboxCapabilityClient,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnavailable,
    make_toolbox_client,
)

if TYPE_CHECKING:
    from docstruct.policy import FusionPolicy


def _artifact_endpoint_urls(*clients: ToolboxCapabilityClient | None) -> set[str]:
    """Collect deployment URLs, including the legacy single-base-url fallback."""
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
    return urls


def _one_artifact_endpoint(*clients: ToolboxCapabilityClient | None) -> bool:
    """IDs are reusable only within one configured Toolbox deployment.

    Multiple URLs represent independent deployments (ADR-0006), so the source
    must accompany extraction instead of relying on an upload client choosing
    the same deployment. A single URL may address a shared-storage balancer.
    """
    return len(_artifact_endpoint_urls(*clients)) <= 1


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

    def extract(self, source_path: Path, *, dual_fusion: bool = True) -> ToolboxExtraction:
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
        try:
            # Inspect each primary/upload client's URLs once. The final policy
            # uses the actual upload client, which may differ from an injected
            # structure client even when each has only one endpoint.
            structure_urls = (
                _artifact_endpoint_urls(structure) if self.use_artifact_store else set()
            )
            if artifacts is None and self.use_artifact_store and len(structure_urls) <= 1:
                artifacts = make_toolbox_client(ToolboxArtifactClient)
            use_artifact_store = (
                self.use_artifact_store
                and artifacts is not None
                and len(structure_urls | _artifact_endpoint_urls(artifacts)) <= 1
            )
            return await self._extract_with(
                structure, artifacts, source_path,
                use_artifact_store=use_artifact_store,
                dual_fusion=dual_fusion,
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
        use_artifact_store: bool,
        dual_fusion: bool = True,
    ) -> ToolboxExtraction:
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Documento não encontrado: {source_path}")

        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()

        artifact_id: str | None = None
        upload_error: str | None = None
        if self.use_artifact_store and not use_artifact_store:
            logger.info(t(LOG_ARTIFACT_STORE_DIRECT_INPUT))
        if use_artifact_store and artifacts is not None:
            try:
                artifact_id = await artifacts.upload(source_path)
            except (ToolboxTimeout, ToolboxProviderUnavailable) as exc:
                upload_error = type(exc).__name__
                use_artifact_store = False
                logger.warning(
                    t(LOG_ARTIFACT_UPLOAD_DEGRADED).format(error=upload_error)
                )
            else:
                logger.info(
                    "Toolbox: artifact {} stored ({})", artifact_id, source_path.name
                )

        extraction_failures: dict[str, str] = {}
        primary_error: ToolboxError | None = None
        final_provider = structure.provider
        final_base_url = structure.base_url
        dual_enabled = (
            settings.fusion_mode == "dual"
            and dual_fusion
            and settings.fusion_secondary_provider != structure.provider
        )
        try:
            result = await structure.extract_structure(
                file_path=None if artifact_id else source_path,
                artifact_id=artifact_id,
                language="pt-BR",
                use_remote_cache=self.use_remote_cache,
            )
        except ToolboxError as exc:
            if not dual_enabled or not _provider_failure(exc):
                raise
            primary_error = exc
            extraction_failures[structure.provider] = type(exc).__name__
            result = None
            logger.warning(
                t(LOG_STRUCTURAL_PROVIDER_DEGRADED).format(
                    provider=structure.provider, error=type(exc).__name__
                )
            )
        if settings.fusion_mode == "dual" and dual_fusion:
            secondary_provider = settings.fusion_secondary_provider
            if secondary_provider == structure.provider:
                result = {**result, "fusion": {
                    "status": "skipped", "providers": [structure.provider],
                    "failed_providers": [], "reason": "identical-providers",
                }}
                logger.warning(
                    t(LOG_DUAL_FUSION_SKIPPED_IDENTICAL_PROVIDERS).format(
                        provider=secondary_provider
                    )
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
                    if artifact_id is not None and secondary_artifact_id is None:
                        logger.info(t(LOG_ARTIFACT_STORE_DIRECT_INPUT))
                    secondary_result = await secondary_client.extract_structure(
                        file_path=None if secondary_artifact_id else source_path,
                        artifact_id=secondary_artifact_id,
                        language="pt-BR",
                        use_remote_cache=self.use_remote_cache,
                    )
                except ToolboxError as exc:
                    # With the primary's result in hand the comparison is only
                    # a gain, so any secondary failure degrades instead of
                    # discarding a complete extraction.
                    if primary_error is not None:
                        if not _provider_failure(exc):
                            raise exc from primary_error
                        raise ToolboxUnavailable(
                            [
                                (
                                    f"{structure.base_url} ({structure.provider})",
                                    primary_error,
                                ),
                                (
                                    f"{secondary_client.base_url} "
                                    f"({secondary_provider})",
                                    exc,
                                ),
                            ]
                        ) from exc
                    extraction_failures[secondary_provider] = type(exc).__name__
                    result = {**result, "fusion": {
                        "status": "degraded",
                        "providers": [structure.provider],
                        "failed_providers": [secondary_provider],
                        "reason": type(exc).__name__,
                    }}
                    logger.warning(
                        t(LOG_STRUCTURAL_PROVIDER_DEGRADED).format(
                            provider=secondary_provider, error=type(exc).__name__
                        )
                    )
                else:
                    if result is None:
                        result = {**secondary_result, "fusion": {
                            "status": "degraded",
                            "providers": [secondary_provider],
                            "failed_providers": [structure.provider],
                            "reason": type(primary_error).__name__,
                        }}
                        final_provider = secondary_provider
                        final_base_url = secondary_client.base_url
                    else:
                        fusion = fuse_extraction_payloads(
                            result,
                            secondary_result,
                            primary_provider=structure.provider,
                            secondary_provider=secondary_provider,
                            policy=self.fusion_policy,
                        )
                        reuse = _persist_fusion_reuse(
                            source_path, fusion, self.fusion_policy
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
                            "fusion_reuse": reuse,
                            "fusion": {"status": "complete", "providers": [structure.provider, secondary_provider], "failed_providers": []},
                            "fusion_stats": fusion["fusion_stats"],
                            "fusion_evidence": fusion["fusion_evidence"],
                            "secondary_extraction": _persist_secondary_extraction(
                                secondary_result, secondary_provider, replaced
                            ),
                        }
                finally:
                    await secondary_client.close()

        assert result is not None
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
                "fusion": result.get("fusion"),
                "fusion_reuse": result.get("fusion_reuse"),
                "fusion_policy": asdict(self.fusion_policy) if self.fusion_policy else None,
                "ocr": self.enable_ocr,
                "table_structure": True,
                "remote_services": True,
                "toolbox_base_url": final_base_url,
                "toolbox_provider": final_provider,
                **(
                    {
                        "extraction_degraded": True,
                        "extraction_failures": extraction_failures,
                    }
                    if extraction_failures
                    else {}
                ),
                "use_artifact_store": use_artifact_store,
                **({"artifact_upload_error": upload_error} if upload_error else {}),
                "use_remote_cache": self.use_remote_cache,
                "artifact_id": artifact_id,
                "cache_key": cache_key,
            },
            artifact_id=artifact_id,
            cache_key=cache_key,
        )


def _persist_fusion_reuse(
    source_path: Path, payload: dict,
    policy: FusionPolicy | None,
) -> dict:
    from dataclasses import asdict

    from docstruct.policy import FusionPolicy

    from backend.services.cache import _file_hash, processing_cache_configuration

    content = json.dumps({
        "source_sha256": _file_hash(source_path),
        "configuration": processing_cache_configuration(),
        "policy": asdict(policy or FusionPolicy()),
        "payload": payload,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    path = settings.data_dir / "artifacts" / "fusion" / f"inputs-{digest}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError:
        logger.warning("Could not persist fusion evidence; extraction will need to run again")
        return {}
    return {"path": str(path), "sha256": digest}


def _provider_failure(exc: ToolboxError) -> bool:
    """Whether ``exc`` is a provider failure another provider may not share.

    Timeouts and unavailability, plus the bare ``ToolboxError`` the SDK raises
    for unmapped statuses such as 500. A rejection of the document itself
    (media type, invalid input, contract, authentication) is permanent.
    """
    return isinstance(exc, (ToolboxTimeout, ToolboxProviderUnavailable)) or (
        type(exc) is ToolboxError
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
