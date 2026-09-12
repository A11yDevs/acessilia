from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.config.settings import settings
from backend.tools.toolbox_client import ToolboxClient


@dataclass(frozen=True)
class ToolboxExtraction:
    """Resultado da extração via Toolbox, análogo a DoclingExtraction.

    Em vez de um objeto docling.Document, carrega o JSON completo da resposta
    da Toolbox para que o builder possa iterar sobre elements/pages diretamente.
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

    Interface compatível com DoclingManifestExtractor.extract(source_path).
    O método extract() é síncrono para compatibilidade com
    InformationalStructuralAgent.process() que roda dentro de asyncio.to_thread.
    """

    def __init__(
        self,
        *,
        client: ToolboxClient | None = None,
        enable_ocr: bool = True,
        use_artifact_store: bool | None = None,
        use_remote_cache: bool | None = None,
    ) -> None:
        self._client = client or ToolboxClient()
        self.enable_ocr = enable_ocr
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

    @property
    def client(self) -> ToolboxClient:
        return self._client

    def extract(self, source_path: Path) -> ToolboxExtraction:
        """Extrai a estrutura de um documento usando a Toolbox (síncrono).

        Executa chamadas HTTP assíncronas via asyncio.run() em thread separada,
        compatível com o fluxo existente que chama extract() dentro de
        asyncio.to_thread().
        """
        return asyncio.run(self._extract_async(source_path))

    async def _extract_async(self, source_path: Path) -> ToolboxExtraction:
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Documento não encontrado: {source_path}")

        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()

        artifact_id: str | None = None
        if self.use_artifact_store:
            artifact_id = await self._client.upload_artifact(source_path)

        result = await self._client.extract_structure(
            file_path=None if artifact_id else source_path,
            artifact_id=artifact_id,
            language="pt-BR",
            use_remote_cache=self.use_remote_cache,
        )

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
                "toolbox_base_url": self._client.base_url,
                "toolbox_provider": self._client.provider,
                "use_artifact_store": self.use_artifact_store,
                "use_remote_cache": self.use_remote_cache,
                "artifact_id": artifact_id,
                "cache_key": cache_key,
            },
            artifact_id=artifact_id,
            cache_key=cache_key,
        )