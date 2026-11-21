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
    ToolboxContractViolation,
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


def _validated_structure_result(result: Any, *, provider: str) -> dict[str, Any]:
    """The extraction envelope, refusing a non-object, a non-succeeded status,
    a missing or non-object document, or a non-object provenance.

    The shipped client already rejects a non-object HTTP body, but an injected
    or duck-typed client can still answer ``None``. Treating that as a payload
    would let a silent ``None`` reach the manifest (or a bare assert stand in
    for a typed failure) instead of the recordable provider error (#673). The
    status check keeps a failed envelope out of the manifest, and the provenance
    check keeps a non-mapping provenance out (#698).
    """
    if not isinstance(result, dict):
        raise ToolboxContractViolation(
            f"{provider} returned {type(result).__name__}, not an extraction envelope"
        )
    status = result.get("status")
    if status != "succeeded":
        raise ToolboxContractViolation(
            f"{provider} answered with status={status!r}, not 'succeeded'"
        )
    document = result.get("document")
    if not isinstance(document, dict):
        raise ToolboxContractViolation(
            f"{provider} answered without a document object: {type(document).__name__}"
        )
    provenance = result.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ToolboxContractViolation(
            f"{provider} answered with a non-object provenance: "
            f"{type(provenance).__name__}"
        )
    return result


def _record_provider_failure(
    provider: str, exc: ToolboxError, extraction_failures: dict[str, str]
) -> None:
    """Record and log one provider's failure so the run is marked degraded.

    ``exc`` may be a transport error classified by ``_provider_failure``, a
    ``ToolboxContractViolation`` raised by ``_validated_structure_result`` for a
    malformed answer, or any secondary failure once the primary result is in
    hand; all are per-provider failures for this record.
    """
    extraction_failures[provider] = type(exc).__name__
    logger.warning(
        t(LOG_STRUCTURAL_PROVIDER_DEGRADED).format(
            provider=provider, error=type(exc).__name__
        )
    )


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

        artifact_id, use_artifact_store, upload_error = await self._upload_source_artifact(
            artifacts,
            source_path,
            use_artifact_store=use_artifact_store,
            toolbox_config=toolbox_config,
            operations=operations,
        )

        extraction_failures: dict[str, str] = {}
        primary_provider = structure.provider or "primary"
        final_provider = primary_provider
        final_base_url = structure.base_url
        dual_enabled = (
            fusion_config.mode == "dual"
            and dual_fusion
            and fusion_config.secondary_provider != primary_provider
        )
        result, primary_error = await self._extract_primary(
            structure,
            source_path,
            artifact_id=artifact_id,
            toolbox_config=toolbox_config,
            operations=operations,
            dual_enabled=dual_enabled,
            extraction_failures=extraction_failures,
            primary_provider=primary_provider,
        )
        if fusion_config.mode == "dual" and dual_fusion:
            result, final_provider, final_base_url = await self._apply_dual_extraction(
                result,
                primary_error=primary_error,
                structure=structure,
                primary_provider=primary_provider,
                artifacts=artifacts,
                source_path=source_path,
                artifact_id=artifact_id,
                fusion_config=fusion_config,
                toolbox_config=toolbox_config,
                data_dir=data_dir,
                started_clock=started_clock,
                operations=operations,
                extraction_failures=extraction_failures,
            )

        if result is None:
            # Defensive: the paths above either return a validated envelope,
            # raise, or hand None to _apply_dual_extraction (which returns a
            # document or raises). Keep a typed error instead of an assert that
            # ``python -O`` would strip (#673).
            raise primary_error or ToolboxContractViolation(
                "The structure extraction produced no document"
            )
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
            configuration=self._build_extraction_configuration(
                result,
                final_provider=final_provider,
                final_base_url=final_base_url,
                extraction_failures=extraction_failures,
                use_artifact_store=use_artifact_store,
                upload_error=upload_error,
                toolbox_config=toolbox_config,
                artifact_id=artifact_id,
                cache_key=cache_key,
            ),
            artifact_id=artifact_id,
            cache_key=cache_key,
        )

    async def _upload_source_artifact(
        self,
        artifacts: ToolboxArtifactClient | None,
        source_path: Path,
        *,
        use_artifact_store: bool,
        toolbox_config: ToolboxConfig,
        operations: RemoteOperations | None,
    ) -> tuple[str | None, bool, str | None]:
        if toolbox_config.use_artifact_store and not use_artifact_store:
            logger.info(t(LOG_ARTIFACT_STORE_DIRECT_INPUT))
        if not (use_artifact_store and artifacts is not None):
            return None, use_artifact_store, None
        try:
            with self._remote_operation("upload", operations):
                artifact_id = await artifacts.upload(source_path)
        except (ToolboxTimeout, ToolboxProviderUnavailable) as exc:
            upload_error = type(exc).__name__
            logger.warning(
                t(LOG_ARTIFACT_UPLOAD_DEGRADED).format(error=upload_error)
            )
            return None, False, upload_error
        logger.info(
            "Toolbox: artifact {} stored ({})", artifact_id, source_path.name
        )
        return artifact_id, use_artifact_store, None

    async def _extract_primary(
        self,
        structure: ToolboxStructureClient,
        source_path: Path,
        *,
        artifact_id: str | None,
        toolbox_config: ToolboxConfig,
        operations: RemoteOperations | None,
        dual_enabled: bool,
        extraction_failures: dict[str, str],
        primary_provider: str,
    ) -> tuple[dict[str, Any] | None, ToolboxError | None]:
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
            _record_provider_failure(primary_provider, exc, extraction_failures)
            return None, exc
        # Validate outside the client `except`: a contract violation raised by
        # the transport stays permanent, while a provider's malformed answer can
        # differ by provider and degrades to the secondary (#673).
        try:
            return _validated_structure_result(
                result, provider=primary_provider
            ), None
        except ToolboxContractViolation as exc:
            if not dual_enabled:
                raise
            _record_provider_failure(primary_provider, exc, extraction_failures)
            return None, exc

    async def _apply_dual_extraction(
        self,
        primary_result: dict[str, Any] | None,
        *,
        primary_error: ToolboxError | None,
        structure: ToolboxStructureClient,
        primary_provider: str,
        artifacts: ToolboxArtifactClient | None,
        source_path: Path,
        artifact_id: str | None,
        fusion_config: FusionConfig,
        toolbox_config: ToolboxConfig,
        data_dir: Path,
        started_clock: float,
        operations: RemoteOperations | None,
        extraction_failures: dict[str, str],
    ) -> tuple[dict[str, Any], str, str]:
        secondary_provider = fusion_config.secondary_provider
        if secondary_provider == primary_provider:
            if primary_result is None:
                raise ToolboxContractViolation(
                    "Identical providers reported no primary extraction"
                )
            skipped = {
                **primary_result,
                "fusion": {
                    "status": "skipped",
                    "providers": [primary_provider],
                    "failed_providers": [],
                    "reason": "identical-providers",
                },
            }
            logger.warning(
                t(LOG_DUAL_FUSION_SKIPPED_IDENTICAL_PROVIDERS).format(
                    provider=secondary_provider
                )
            )
            return skipped, primary_provider, structure.base_url

        secondary_client = make_toolbox_client(
            ToolboxStructureClient, toolbox_config, provider=secondary_provider
        )
        try:
            secondary_result = await self._extract_secondary(
                structure,
                artifacts,
                secondary_client,
                source_path,
                artifact_id=artifact_id,
                secondary_provider=secondary_provider,
                toolbox_config=toolbox_config,
                started_clock=started_clock,
                has_primary=primary_result is not None,
                operations=operations,
            )
        except ToolboxError as exc:
            degraded = self._handle_secondary_failure(
                exc,
                primary_error=primary_error,
                primary_result=primary_result,
                structure=structure,
                primary_provider=primary_provider,
                secondary_client=secondary_client,
                secondary_provider=secondary_provider,
                extraction_failures=extraction_failures,
            )
            return degraded, primary_provider, structure.base_url
        finally:
            await secondary_client.close()

        if primary_result is None:
            degraded = {
                **secondary_result,
                "fusion": {
                    "status": "degraded",
                    "providers": [secondary_provider],
                    "failed_providers": [primary_provider],
                    "reason": type(primary_error).__name__,
                },
            }
            return degraded, secondary_provider, secondary_client.base_url

        fused = self._fuse_dual_extractions(
            primary_result,
            secondary_result,
            source_path=source_path,
            primary_provider=primary_provider,
            secondary_provider=secondary_provider,
            fusion_config=fusion_config,
            toolbox_config=toolbox_config,
            data_dir=data_dir,
        )
        return fused, primary_provider, structure.base_url

    async def _extract_secondary(
        self,
        structure: ToolboxStructureClient,
        artifacts: ToolboxArtifactClient | None,
        secondary_client: ToolboxStructureClient,
        source_path: Path,
        *,
        artifact_id: str | None,
        secondary_provider: str,
        toolbox_config: ToolboxConfig,
        started_clock: float,
        has_primary: bool,
        operations: RemoteOperations | None,
    ) -> dict[str, Any]:
        secondary_artifact_id = (
            artifact_id
            if one_artifact_endpoint(structure, artifacts, secondary_client)
            else None
        )
        if artifact_id is not None and secondary_artifact_id is None:
            logger.info(t(LOG_ARTIFACT_STORE_DIRECT_INPUT))
        # With the primary's result in hand, the secondary gets only the time
        # left before the extraction-wide deadline, so a hung secondary degrades
        # instead of discarding the complete primary (#603). Without it, the
        # secondary is the only source and keeps the whole deadline.
        budget = (
            _secondary_budget(toolbox_config, started_clock) if has_primary else None
        )
        with self._remote_operation("secondary", operations):
            result = await _within(
                budget,
                secondary_client.extract_structure(
                    file_path=None if secondary_artifact_id else source_path,
                    artifact_id=secondary_artifact_id,
                    language="pt-BR",
                    use_remote_cache=toolbox_config.use_remote_cache,
                ),
                provider=secondary_provider,
            )
        return _validated_structure_result(result, provider=secondary_provider)

    @staticmethod
    def _handle_secondary_failure(
        exc: ToolboxError,
        *,
        primary_error: ToolboxError | None,
        primary_result: dict[str, Any] | None,
        structure: ToolboxStructureClient,
        primary_provider: str,
        secondary_client: ToolboxStructureClient,
        secondary_provider: str,
        extraction_failures: dict[str, str],
    ) -> dict[str, Any]:
        # With the primary's result in hand the comparison is only a gain, so
        # any secondary failure degrades instead of discarding a complete extraction.
        if primary_error is not None:
            if not _provider_failure(exc):
                raise exc from primary_error
            raise ToolboxUnavailable(
                [
                    (f"{structure.base_url} ({primary_provider})", primary_error),
                    (f"{secondary_client.base_url} ({secondary_provider})", exc),
                ]
            ) from exc
        if primary_result is None:
            raise ToolboxContractViolation(
                "The structure extraction produced no primary document"
            )
        _record_provider_failure(secondary_provider, exc, extraction_failures)
        return {
            **primary_result,
            "fusion": {
                "status": "degraded",
                "providers": [primary_provider],
                "failed_providers": [secondary_provider],
                "reason": type(exc).__name__,
            },
        }

    def _fuse_dual_extractions(
        self,
        primary_result: dict[str, Any],
        secondary_result: dict[str, Any],
        *,
        source_path: Path,
        primary_provider: str,
        secondary_provider: str,
        fusion_config: FusionConfig,
        toolbox_config: ToolboxConfig,
        data_dir: Path,
    ) -> dict[str, Any]:
        from acessilia_core.pipeline.fusion import (
            apply_page_routes,
            fuse_extraction_payloads,
        )

        fusion = fuse_extraction_payloads(
            primary_result,
            secondary_result,
            primary_provider=primary_provider,
            secondary_provider=secondary_provider,
            policy=self.fusion_policy,
        )
        reuse = _persist_fusion_reuse(
            source_path,
            fusion,
            self.fusion_policy,
            data_dir=data_dir,
            identity=fusion_reuse_identity(fusion_config, toolbox_config),
        )
        replaced: dict[int, list[dict[str, Any]]] = {}
        result = primary_result
        if fusion_config.apply_page_routes:
            result, replaced = apply_page_routes(
                primary_result,
                secondary_result,
                fusion["fusion_evidence"]["pages"],
                secondary_provider=secondary_provider,
            )
        return {
            **result,
            "fusion_reuse": reuse,
            "fusion": {
                "status": "complete",
                "providers": [primary_provider, secondary_provider],
                "failed_providers": [],
            },
            "fusion_stats": fusion["fusion_stats"],
            "fusion_evidence": fusion["fusion_evidence"],
            "secondary_extraction": _persist_secondary_extraction(
                secondary_result,
                secondary_provider,
                replaced,
                data_dir=data_dir,
            ),
        }

    def _build_extraction_configuration(
        self,
        result: dict[str, Any],
        *,
        final_provider: str,
        final_base_url: str,
        extraction_failures: dict[str, str],
        use_artifact_store: bool,
        upload_error: str | None,
        toolbox_config: ToolboxConfig,
        artifact_id: str | None,
        cache_key: str | None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "fusion": result.get("fusion"),
            "fusion_reuse": result.get("fusion_reuse"),
            "fusion_policy": asdict(self.fusion_policy) if self.fusion_policy else None,
            "ocr": self.enable_ocr,
            "table_structure": True,
            "remote_services": True,
            "toolbox_base_url": final_base_url,
            "toolbox_provider": final_provider,
            "use_artifact_store": use_artifact_store,
            "use_remote_cache": toolbox_config.use_remote_cache,
            "artifact_id": artifact_id,
            "cache_key": cache_key,
        }
        if extraction_failures:
            config["extraction_degraded"] = True
            config["extraction_failures"] = extraction_failures
        if upload_error:
            config["artifact_upload_error"] = upload_error
        return config


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
