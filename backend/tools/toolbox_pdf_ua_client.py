"""Cliente especializado para a capacidade document.export.pdf_ua da Toolbox.

Envia o AST Pandoc (JSON) à Toolbox, que renderiza o PDF/UA com Pandoc e TeX
Live fixados numa imagem própria. O PDF não volta embutido na resposta: a
Toolbox o grava no armazenamento de artefatos (MinIO) e devolve só o
``artifact_id``, que este cliente baixa por ``GET /v1/artifacts/{id}``.

O cache de execução da Toolbox (Valkey) cobre o AST, o idioma e as versões do
toolchain; reexportar o mesmo documento reaproveita o PDF sem rodar o LaTeX.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxCapabilityClient,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    _raise_for_error,
    run_sync,
)

CAPABILITY = "document.export.pdf_ua"
PDF_MEDIA_TYPE = "application/pdf"
# O nome do upload entra na chave de cache da Toolbox: um nome fixo evita que
# o mesmo documento, exportado por jobs diferentes, deixe de acertar o cache.
UPLOAD_FILENAME = "document.ast.json"
# Únicas chaves do AST que o pandoc lê.
PANDOC_AST_KEYS = ("pandoc-api-version", "meta", "blocks")


def pandoc_payload(ast: dict[str, Any]) -> bytes:
    """Serializa só a parte do AST que o pandoc lê, de forma determinística.

    ``build_pandoc_ast`` anexa ``source_document`` (o documento canônico, com
    um ``id`` aleatório). O pandoc o ignora, mas ele mudaria o hash do upload a
    cada execução e o cache da Toolbox nunca seria aproveitado.
    """
    trimmed = {key: ast[key] for key in PANDOC_AST_KEYS if key in ast}
    return json.dumps(trimmed, ensure_ascii=False, sort_keys=True).encode("utf-8")


class ToolboxPdfUaClient(ToolboxCapabilityClient):
    """Cliente para exportação PDF/UA via Acessilia Toolbox."""

    provider_key = "toolbox_pdf_ua_provider"

    async def export(
        self,
        ast: dict[str, Any],
        output_path: Path,
        *,
        lang: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """Renderiza ``ast`` em PDF/UA na Toolbox e grava o PDF em ``output_path``.

        Args:
            ast: AST Pandoc em JSON, já sem imagens (só texto alternativo).
            output_path: Destino do PDF baixado.
            lang: Etiqueta BCP 47 gravada nos metadados do PDF.
            use_remote_cache: Se False, força nova renderização na Toolbox.

        Returns:
            O ``document`` da resposta (schema artifact/pdf-export@1), com o
            ``artifact_id``, o tamanho e as versões do toolchain.
        """
        use_cache = (
            use_remote_cache
            if use_remote_cache is not None
            else settings.toolbox_use_remote_cache
        )
        result = await self._execute(
            CAPABILITY,
            upload=(UPLOAD_FILENAME, pandoc_payload(ast), "application/json"),
            parameters={"lang": lang},
            no_cache=not use_cache,
        )

        document = result.get("document")
        if not isinstance(document, dict):
            raise ToolboxContractViolation(
                f"Resposta de {CAPABILITY} sem campo 'document'"
            )
        artifact_id = document.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ToolboxContractViolation(
                f"Resposta de {CAPABILITY} sem artifact_id do PDF"
            )
        if document.get("media_type") != PDF_MEDIA_TYPE:
            raise ToolboxContractViolation(
                f"{CAPABILITY} devolveu {document.get('media_type')!r}, esperado PDF"
            )

        await self._download(artifact_id, output_path)

        provenance = result.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        logger.info(
            "Toolbox: {} concluído ({} bytes, cache_hit={}, {} ms)",
            CAPABILITY,
            document.get("size_bytes", "?"),
            provenance.get("cache_hit", False),
            provenance.get("duration_ms", "?"),
        )
        return document

    async def _download(self, artifact_id: str, output_path: Path) -> None:
        """Baixa o PDF e confere que os bytes têm o hash do ``artifact_id``.

        O id é o SHA-256 do conteúdo, então a conferência detecta um download
        truncado ou um objeto corrompido antes de entregá-lo ao usuário.
        """
        try:
            response = await self._client.get(f"/v1/artifacts/{artifact_id}")
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao baixar o PDF {artifact_id} da Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e
        _raise_for_error(response, "artifact.retrieve")

        content = response.content
        digest = hashlib.sha256(content).hexdigest()
        if artifact_id.removeprefix("sha256:") != digest:
            raise ToolboxContractViolation(
                f"PDF baixado não corresponde ao artifact_id {artifact_id}"
            )
        if not content.startswith(b"%PDF-"):
            raise ToolboxContractViolation(
                f"Artefato {artifact_id} não é um PDF"
            )

        # Escrita atômica: um download interrompido não deixa PDF parcial.
        partial = output_path.with_name(f".{output_path.name}.part")
        partial.write_bytes(content)
        os.replace(partial, output_path)



def toolbox_export_pdf_ua(
    ast: dict[str, Any], output_path: Path, *, lang: str = "pt-BR"
) -> dict[str, Any]:
    """Versão síncrona de :meth:`ToolboxPdfUaClient.export` para o exportador.

    O cliente é criado e fechado dentro da corrotina: ``run_sync`` pode rodá-la
    num event loop novo, e a conexão HTTP não deve sobreviver a ele.
    """

    async def _export() -> dict[str, Any]:
        client = ToolboxPdfUaClient()
        try:
            return await client.export(ast, output_path, lang=lang)
        finally:
            await client.close()

    return run_sync(_export())


__all__ = ["ToolboxPdfUaClient", "toolbox_export_pdf_ua"]
