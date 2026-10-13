"""Inspeção determinística de mídia — fallback local do media.inspect.

Reproduz, sem dependências de ML, a classificação do provider
``pure-media-inspect`` da Toolbox (PR acessilia-toolbox#33), usando apenas
Pillow e PyMuPDF (já dependências do projeto). O dicionário retornado segue o
schema ``artifact/media-inspection@1``, de modo que o consumidor no orquestrador
seja agnóstico à origem do sinal (Toolbox remota ou fallback local).

Nada é adivinhado: um valor que não pode ser medido é reportado como ``None``
junto do mecanismo que o produziu.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxError

# Limiar mínimo de aresta (px) para uma imagem ser considerada página de
# documento. Miniaturas e ícones não devem ser classificados como página.
MIN_SCANNED_PAGE_PX = 200

# Páginas A4 e US Letter retrato caem nesta faixa de proporção largura/altura.
SCANNED_PAGE_ASPECT = (0.65, 0.78)

# Formato de contêiner -> MIME type (o map de Pillow omite formatos não
# embutidos no binário em execução, então o map é explícito).
MEDIA_TYPE_BY_FORMAT = {
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


def _dimensions(width: int, height: int) -> dict[str, Any]:
    return {
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 4),
    }


def _pdf_page_count_from_content(payload: bytes) -> int:
    """Conta objetos de página varrendo o content-stream do PDF (último recurso)."""
    counted = payload.count(b"/Type /Page") - payload.count(b"/Type /Pages")
    return max(1, counted)


def _inspect_pdf(
    payload: bytes, filename: str, media_type: str
) -> dict[str, Any] | None:
    """Inspeciona um PDF, usando PyMuPDF quando disponível.

    Retorna ``None`` quando o payload não carrega estrutura PDF verificável.
    """
    import fitz

    page_count = _pdf_page_count_from_content(payload)
    page_count_source: str | None = "content_stream_scan"
    dimensions: dict[str, Any] | None = None
    dimensions_source: str | None = None
    verified = payload.startswith(b"%PDF-")

    document = None
    try:
        document = fitz.open(stream=payload, filetype="pdf")
        opened_pages = len(document)
        if opened_pages > 0:
            verified = True
            page_count = opened_pages
            page_count_source = "pymupdf"
            frame = document[0].rect
            width, height = round(frame.width), round(frame.height)
            if width > 0 and height > 0:
                dimensions = _dimensions(width, height)
                dimensions_source = "pymupdf"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Falha ao abrir PDF via PyMuPDF: %s", exc)
    finally:
        if document is not None:
            document.close()

    if not verified:
        return None

    return {
        "media_type": "application/pdf",
        "declared_media_type": media_type or None,
        "file_size_bytes": len(payload),
        "is_image": False,
        "is_pdf": True,
        "page_count": page_count,
        "page_count_source": page_count_source,
        "dimensions": dimensions,
        "dimensions_source": dimensions_source,
        "color_mode": None,
        "format": "PDF",
        "artifact_nature": "paginated_document",
        "requires_visual_inspection": False,
        "metadata": {"filename": filename},
    }


def _unsupported_media(
    payload: bytes, filename: str, media_type: str
) -> dict[str, Any]:
    """Reporta um artefato cujo contêiner não pôde ser identificado."""
    return {
        "media_type": "application/octet-stream",
        "declared_media_type": media_type or None,
        "file_size_bytes": len(payload),
        "is_image": False,
        "is_pdf": False,
        "page_count": 1,
        "page_count_source": None,
        "dimensions": None,
        "dimensions_source": None,
        "color_mode": None,
        "format": None,
        "artifact_nature": "unknown",
        "requires_visual_inspection": False,
        "metadata": {"filename": filename},
    }


def inspect_media_payload(
    payload: bytes,
    filename: str,
    media_type: str,
) -> dict[str, Any]:
    """Inspeção determinística sobre o payload de mídia.

    Args:
        payload: bytes brutos do artefato.
        filename: nome original do arquivo (para extensão/metadados).
        media_type: MIME type declarado pelo chamador.

    Returns:
        Dict compatível com artifact/media-inspection@1.
    """
    from PIL import Image, UnidentifiedImageError

    size_bytes = len(payload)
    is_pdf_signal = (
        media_type == "application/pdf"
        or filename.lower().endswith(".pdf")
        or payload.startswith(b"%PDF-")
    )
    if is_pdf_signal:
        document = _inspect_pdf(payload, filename, media_type)
        if document is not None:
            return document
        return _unsupported_media(payload, filename, media_type)

    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            if width < 1 or height < 1:
                return _unsupported_media(payload, filename, media_type)
            frame_count = max(1, int(getattr(image, "n_frames", 1)))
            format_name = image.format or "UNKNOWN"
            color_mode = image.mode
            detected_type = MEDIA_TYPE_BY_FORMAT.get(
                format_name, f"image/{format_name.lower()}"
            )
    except UnidentifiedImageError:
        return _unsupported_media(payload, filename, media_type)

    aspect_ratio = round(width / height, 4)
    is_page_sized = min(width, height) >= MIN_SCANNED_PAGE_PX
    if frame_count > 1:
        nature = "paginated_document"
    elif (
        is_page_sized
        and SCANNED_PAGE_ASPECT[0] <= aspect_ratio <= SCANNED_PAGE_ASPECT[1]
    ):
        nature = "scanned_page"
    else:
        nature = "standalone_image"

    return {
        "media_type": detected_type,
        "declared_media_type": media_type or None,
        "file_size_bytes": size_bytes,
        "is_image": True,
        "is_pdf": False,
        "page_count": frame_count,
        "page_count_source": "pillow",
        "dimensions": _dimensions(width, height),
        "dimensions_source": "pillow",
        "color_mode": color_mode,
        "format": format_name,
        "artifact_nature": nature,
        "requires_visual_inspection": nature != "scanned_page",
        "metadata": {"filename": filename},
    }


async def inspect_source_media(
    source_path: Path,
    *,
    client: Any | None = None,
    use_remote_cache: bool | None = None,
) -> dict[str, Any] | None:
    """Inspeciona a mídia do arquivo de origem (Toolbox-first + fallback local).

    Tenta a capacidade ``media.inspect`` na Toolbox; se a Toolbox estiver
    indisponível (ou retornar erro), degrada para a heurística local
    determinística. Retorna ``None`` apenas quando nenhuma das duas vias
    consegue produzir um resultado.

    Args:
        source_path: caminho do arquivo a inspecionar.
        client: instância opcional de ToolboxMediaInspectClient (evita recriar).
        use_remote_cache: repassado ao cliente da Toolbox.

    Returns:
        Dict de inspeção (artifact/media-inspection@1) ou None.
    """
    source_path = source_path.resolve()
    if not source_path.is_file():
        return None

    from backend.config.settings import settings
    from backend.tools.toolbox_client import _media_type

    media_type = _media_type(source_path)
    filename = source_path.name

    if settings.toolbox_media_inspect_enabled:
        from backend.tools.toolbox_media_inspect_client import (
            ToolboxMediaInspectClient,
        )

        owned_client = client is None
        inspect_client = client or ToolboxMediaInspectClient()
        try:
            result = await inspect_client.inspect(
                file_path=source_path,
                use_remote_cache=use_remote_cache,
            )
            if isinstance(result, dict):
                return result
        except ToolboxError as exc:
            logger.warning(
                "Toolbox media.inspect indisponível, usando fallback local: %s",
                exc,
            )
        finally:
            if owned_client:
                await inspect_client.close()

    try:
        return inspect_media_payload(
            source_path.read_bytes(),
            filename,
            media_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Inspeção local de mídia falhou para %s: %s",
            filename,
            exc,
        )
        return None
