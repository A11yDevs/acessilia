from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from acessilia_sdk.toolbox import (
    artifact_endpoint_urls,
    one_artifact_endpoint,
    operation_context,
)
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient, ToolboxStructureClient

from acessilia_core.run_identity import fusion_reuse_identity
from acessilia_core.config import FusionConfig, PathsConfig, ToolboxConfig
from acessilia_core.ports import OperationKind, RemoteOperations
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_ARTIFACT_STORE_DIRECT_INPUT,
    LOG_ARTIFACT_UPLOAD_DEGRADED,
    LOG_DUAL_FUSION_SKIPPED_IDENTICAL_PROVIDERS,
    LOG_STRUCTURAL_PROVIDER_DEGRADED,
    MSG_TOOLBOX_EXTRACTION_TIMEOUT,
)
from acessilia_core.logger import logger
from acessilia_core.toolbox.toolbox_client import (
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnavailable,
    make_toolbox_client,
)

if TYPE_CHECKING:
    from docstruct.policy import FusionPolicy


@dataclass(frozen=True)
class ToolboxExtraction:
    """Toolbox extraction result.

    Carries the Toolbox response's full JSON, from which the builder reads
    elements and pages directly.
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
    """Manifest extractor that consumes the Acessilia Toolbox over REST.

    It is the core's only manifest extractor: extraction runs on the Toolbox
    (docs/adr/0003). The extract() method is synchronous for compatibility with
    InformationalStructuralAgent.process(), which runs inside asyncio.to_thread.
    """

    def __init__(
        self,
        *,
        client: ToolboxStructureClient | None = None,
        artifact_client: ToolboxArtifactClient | None = None,
        enable_ocr: bool = True,
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

    def extract(
        self,
        source_path: Path,
        *,
        fusion: FusionConfig,
        toolbox: ToolboxConfig,
        paths: PathsConfig,
        operations: RemoteOperations | None,
        dual_fusion: bool = True,
    ) -> ToolboxExtraction:
        """Extract a document's structure using the Toolbox (synchronous).

        Runs the asynchronous HTTP calls via asyncio.run() on a separate thread,
        compatible with the existing flow that calls extract() inside
        asyncio.to_thread(). ``fusion`` is the run's ``FusionConfig`` (mode,
        secondary provider, page routes), and ``toolbox`` its ``ToolboxConfig``
        (the artifact store, the Toolbox cache, the extraction timeout), and
        ``paths`` where the fusion evidence is written. ``operations`` is the
        job's registry of remote calls (ADR-0019), ``None`` outside a job. With
        ``dual_fusion=False`` the
        secondary provider is not called even in dual mode (a presentation).
        """
        timeout = max(1, toolbox.extraction_timeout_seconds)
        try:
            return asyncio.run(
                asyncio.wait_for(
                    self._extract_async(
                        source_path,
                        fusion_config=fusion,
                        toolbox_config=toolbox,
                        data_dir=paths.data_dir,
                        operations=operations,
                        dual_fusion=dual_fusion,
                    ),
                    timeout=timeout,
                )
            )
        except TimeoutError as exc:
            # The deadline cancels the async HTTP work, so the thread returns
            # even when run_blocking is waiting after a job cancellation. It
            # covers upload, retries, failover and both providers; no new
            # attempt starts after it expires.
            message = t(MSG_TOOLBOX_EXTRACTION_TIMEOUT).format(seconds=timeout)
            logger.warning(message)
            raise ToolboxTimeout(message) from exc

    @staticmethod
    @contextmanager
    def _remote_operation(kind: OperationKind, operations: RemoteOperations | None):
        """Register and label one remote call for cancellation (ADR-0019).

        Outside a job (``operations`` is ``None``) there is no registry entry:
        the call keeps the pre-ADR behaviour. Inside a job the operation id
        stays the same across SDK retries and failover, while the SDK gives
        each attempt its own attempt id.
        """
        if operations is None:
            yield
            return
        operation_id = operations.begin(kind)
        try:
            with operation_context(operations.job_id, operation_id):
                yield
        finally:
            operations.finish(operation_id)

    async def _extract_async(
        self,
        source_path: Path,
        *,
        fusion_config: FusionConfig,
        toolbox_config: ToolboxConfig,
        data_dir: Path,
        operations: RemoteOperations | None,
        dual_fusion: bool = True,
    ) -> ToolboxExtraction:
        structure = self._client or make_toolbox_client(ToolboxStructureClient, toolbox_config)
        artifacts = self._artifact_client
        try:
            # Inspect each primary/upload client's URLs once. The final policy
            # uses the actual upload client, which may differ from an injected
            # structure client even when each has only one endpoint.
            structure_urls = (
                artifact_endpoint_urls(structure) if toolbox_config.use_artifact_store else set()
            )
            if (
                artifacts is None
                and toolbox_config.use_artifact_store
                and len(structure_urls) <= 1
            ):
                artifacts = make_toolbox_client(ToolboxArtifactClient, toolbox_config)
            use_artifact_store = (
                toolbox_config.use_artifact_store
                and artifacts is not None
                and len(structure_urls | artifact_endpoint_urls(artifacts)) <= 1
            )
            return await self._extract_with(
                structure, artifacts, source_path,
                use_artifact_store=use_artifact_store,
                fusion_config=fusion_config,
                toolbox_config=toolbox_config,
                data_dir=data_dir,
                operations=operations,
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
        fusion_config: FusionConfig,
        toolbox_config: ToolboxConfig,
        data_dir: Path,
        operations: RemoteOperations | None,
        dual_fusion: bool = True,
    ) -> ToolboxExtraction:
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Document not found: {source_path}")

        started_at = datetime.now(UTC)
        started_clock = perf_counter()

        artifact_id: str | None = None
        upload_error: str | None = None
        if toolbox_config.use_artifact_store and not use_artifact_store:
            logger.info(t(LOG_ARTIFACT_STORE_DIRECT_INPUT))
        if use_artifact_store and artifacts is not None:
            try:
                with self._remote_operation("upload", operations):
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
            fusion_config.mode == "dual"
            and dual_fusion
            and fusion_config.secondary_provider != structure.provider
        )
        try:
            with self._remote_operation("primary", operations):
                result = await structure.extract_structure(
                    file_path=None if artifact_id else source_path,
                    artifact_id=artifact_id,
                    language="pt-BR",
                    use_remote_cache=toolbox_config.use_remote_cache,
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
        if fusion_config.mode == "dual" and dual_fusion:
            secondary_provider = fusion_config.secondary_provider
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
                from acessilia_core.pipeline.fusion import (
                    apply_page_routes,
                    fuse_extraction_payloads,
                )

                secondary_client = make_toolbox_client(
                    ToolboxStructureClient, toolbox_config, provider=secondary_provider
                )
                try:
                    secondary_artifact_id = (
                        artifact_id
                        if one_artifact_endpoint(
                            structure, artifacts, secondary_client
                        )
                        else None
                    )
                    if artifact_id is not None and secondary_artifact_id is None:
                        logger.info(t(LOG_ARTIFACT_STORE_DIRECT_INPUT))
                    # With the primary's result in hand, the secondary gets
                    # only the time left before the extraction-wide deadline,
                    # so a hung secondary degrades instead of discarding the
                    # complete primary (#603). Without it, the secondary is
                    # the only source and keeps the whole deadline.
                    budget = (
                        _secondary_budget(toolbox_config, started_clock)
                        if result is not None
                        else None
                    )
                    with self._remote_operation("secondary", operations):
                        secondary_result = await _within(
                            budget,
                            secondary_client.extract_structure(
                                file_path=None if secondary_artifact_id else source_path,
                                artifact_id=secondary_artifact_id,
                                language="pt-BR",
                                use_remote_cache=toolbox_config.use_remote_cache,
                            ),
                            provider=secondary_provider,
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
                            source_path, fusion, self.fusion_policy, data_dir=data_dir,
                            identity=fusion_reuse_identity(fusion_config, toolbox_config),
                        )
                        replaced: dict[int, list[dict[str, Any]]] = {}
                        if fusion_config.apply_page_routes:
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
                                secondary_result, secondary_provider, replaced,
                                data_dir=data_dir,
                            ),
                        }
                finally:
                    await secondary_client.close()

        assert result is not None
        duration_ms = round((perf_counter() - started_clock) * 1000)
        completed_at = datetime.now(UTC)

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
                "use_remote_cache": toolbox_config.use_remote_cache,
                "artifact_id": artifact_id,
                "cache_key": cache_key,
            },
            artifact_id=artifact_id,
            cache_key=cache_key,
        )


def _source_sha256(source_path: Path) -> str:
    """The source's SHA-256, read in chunks rather than whole (review of #561)."""
    with source_path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _persist_fusion_reuse(
    source_path: Path, payload: dict,
    policy: FusionPolicy | None,
    *,
    data_dir: Path,
    identity: dict,
) -> dict:
    """Store a fused extraction for the dual-provider fusion handler to reuse.

    ``identity`` is the run's :func:`~acessilia_core.run_identity.fusion_reuse_identity`:
    the record keeps it as the provenance of the payload (the fusion options,
    the deployment and providers, the strategy version), and the handler
    reuses the payload only for a run with the same identity (#544).
    """
    from dataclasses import asdict

    from docstruct.policy import FusionPolicy

    content = json.dumps({
        "source_sha256": _source_sha256(source_path),
        "identity": identity,
        "policy": asdict(policy or FusionPolicy()),
        "payload": payload,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    path = data_dir / "artifacts" / "fusion" / f"inputs-{digest}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError:
        logger.warning("Could not persist fusion evidence; extraction will need to run again")
        return {}
    return {"path": str(path), "sha256": digest}


#: Time kept back from the extraction-wide deadline, when the secondary has a
#: complete primary to degrade to, for the work after the secondary answers:
#: fusing the two payloads, routing pages and writing the evidence. That work
#: is synchronous, so the deadline cannot interrupt it; at most this many
#: seconds, and at most a tenth of the deadline.
SECONDARY_RESERVE_SECONDS = 60.0


def _secondary_budget(toolbox: ToolboxConfig, started_clock: float) -> float:
    """Seconds the secondary may take, given a complete primary result (#603).

    The time left before the extraction-wide deadline, which counts from
    ``started_clock``, minus the reserve for the fusion that follows.
    """
    deadline = max(1, toolbox.extraction_timeout_seconds)
    reserve = min(SECONDARY_RESERVE_SECONDS, deadline / 10)
    return deadline - (perf_counter() - started_clock) - reserve


async def _within(budget: float | None, call: Any, *, provider: str) -> Any:
    """Await ``call``, or raise ``ToolboxTimeout`` once ``budget`` seconds pass.

    ``None`` is no budget of its own: the extraction-wide deadline applies.
    The ``ToolboxTimeout`` is a provider failure, so the caller's degradation
    handles it as it does a secondary that timed out on its own.
    """
    if budget is None:
        return await call
    message = (
        f"{provider} did not answer within the {max(budget, 0):.0f} s left "
        "before the extraction deadline"
    )
    if budget <= 0:
        call.close()
        raise ToolboxTimeout(message)
    try:
        return await asyncio.wait_for(call, timeout=budget)
    except TimeoutError as exc:
        raise ToolboxTimeout(message) from exc


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
    *,
    data_dir: Path,
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
    path = data_dir / "artifacts" / "fusion" / f"secondary-{digest[:16]}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError as exc:
        logger.warning(
            "Secondary extraction of {} was not written ({}): {}",
            provider,
            type(exc).__name__,
            exc,
        )
        return {}
    return {"provider": provider, "path": str(path), "sha256": digest}
