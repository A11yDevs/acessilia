import io
from pathlib import Path
from typing import Any, Callable, Coroutine

import fitz
from PIL import Image

from config.settings import settings

if settings.ai_client == "browser":
    from bot.clients.browser_client import client as opencode_client
elif settings.ai_client == "openrouter":
    from bot.clients.openrouter import client as opencode_client
else:
    from bot.clients.opencode import client as opencode_client

from bot.services.cache import get_cached, set_cache
from bot.utils.image_converter import convert_pdf_to_png
from bot.utils.image_enhancer import enhance_image_for_ocr
from bot.utils.logger import logger
from bot.utils.pdf_splitter import split_pdf
from pipeline.structure_parser import parse_text_to_blocks

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Número mínimo de caracteres para considerar que a página tem texto extraível
# (abaixo disso: página escaneada/imagem → usa IA de visão)
_MIN_TEXT_CHARS = settings.pymupdf_text_threshold


def _extract_page_text_and_images(
    page_path: Path,
) -> tuple[str, list[bytes]]:
    """Extrai texto e imagens embutidas de uma página PDF via PyMuPDF.

    Retorna (texto_limpo, lista_de_imagens_bytes).
    """
    doc = fitz.open(page_path)
    try:
        page = doc[0]
        text = page.get_text().strip()
        images: list[bytes] = []
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            if base_image and base_image.get("image"):
                images.append(base_image["image"])
        return text, images
    finally:
        doc.close()


MODE_MAP = {
    "detalhado": "detalhado.txt",
    "medio": "medio.txt",
    "normal": "medio.txt",
    "baixo": "baixo.txt",
    "ocr": "ocr.txt",
}


def _load_system_prompt(mode: str = "medio") -> str:
    filename = MODE_MAP.get(mode, "medio.txt")
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")

    logger.warning(
        "Prompt file not found at {}, falling back to medio",
        prompt_path,
    )
    fallback = PROMPTS_DIR / "medio.txt"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8")

    return (
        "Voce e um sistema de acessibilidade digital. Converta as imagens "
        "recebidas em texto acessivel para leitores de tela em portugues "
        "brasileiro. Descreva elementos visuais e extraia todo o texto "
        "presente."
    )


def _compress_to_jpg(
    image_bytes: bytes,
    max_width: int | None = None,
    quality: int | None = None,
) -> bytes:
    max_width = max_width or settings.max_page_width
    quality = quality or settings.jpg_quality

    img = Image.open(io.BytesIO(image_bytes))

    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        alpha = img.split()[-1] if "A" in img.mode else None
        background.paste(img, mask=alpha)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    width, height = img.size
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)

    output = io.BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


def _page_prompt(
    system_prompt: str,
    total_pages: int,
    page_num: int,
    is_pdf: bool,
) -> str:
    advanced_instructions = (
        "\n\nREGRAS DE FORMATAÇÃO E SEMÂNTICA:\n"
        "1. Se houver imagens, gráficos ou diagramas, forneça a "
        "audiodescrição entre colchetes.\n"
        "2. Preserve a ênfase do texto original usando Markdown apenas "
        "quando necessário.\n"
        "3. Para MATEMÁTICA: linearize fórmulas simples e use LaTeX para "
        "expressões complexas.\n"
        "4. Se um parágrafo termina com hífen ou parece continuar na "
        "próxima página, apenas transcreva-o."
    )

    prompt = system_prompt + advanced_instructions
    if is_pdf:
        prompt += (
            f"\n\nEste e o documento de {total_pages} paginas. "
            f"Voce esta processando a pagina {page_num} de {total_pages}."
        )
    return prompt


class AgenteUnico:
    """Agente unico que processa PDF/imagem pagina por pagina via OpenCode."""

    def __init__(self, mode: str = "medio"):
        self.mode = mode
        self.system_prompt = _load_system_prompt(mode)

    async def executar(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine] | None = None,
        mode: str | None = None,
        structured_output: bool = False,
    ) -> str | dict[str, Any]:
        effective_mode = mode or self.mode
        system_prompt = _load_system_prompt(effective_mode)
        is_pdf = file_path.suffix.lower() == ".pdf"

        if is_pdf:
            if status_callback:
                await status_callback("📄 Separando PDF em paginas...")
            page_pdfs = split_pdf(file_path, tmpdir, settings.max_pages)
        else:
            if status_callback:
                await status_callback("🖼️ Preparando imagem...")
            page_pdfs = [file_path]

        total_pages = len(page_pdfs)
        if total_pages == 0:
            raise RuntimeError("Nenhuma pagina gerada a partir do arquivo")

        logger.info(
            "Processando {} pagina(s) para {}",
            total_pages,
            file_path.name,
        )

        results: list[str] = []
        page_payloads: list[dict[str, Any]] = []

        for index, page_path in enumerate(page_pdfs):
            page_num = index + 1
            if status_callback:
                label = (
                    f"📷 Processando pagina {page_num} de {total_pages}..."
                )
                await status_callback(label)

            page_cache_key = f"page_{page_num}_{effective_mode}"
            cached_page = await get_cached(
                page_path,
                page_cache_key,
                ttl=86400,
            )
            if cached_page:
                logger.info("[pag {}] Cache hit (pulando IA)", page_num)
                results.append(cached_page)
                page_payloads.append(
                    {
                        "page_number": page_num,
                        "file_path": str(page_path),
                        "text": cached_page,
                        "blocks": parse_text_to_blocks(cached_page),
                        "cached": True,
                    }
                )
                continue

            response: str = ""

            # ----------------------------------------------------------
            # Extração determinística via PyMuPDF (PDFs com texto)
            # ----------------------------------------------------------
            page_text: str = ""
            page_images: list[bytes] = []
            if is_pdf:
                page_text, page_images = _extract_page_text_and_images(
                    page_path
                )

            if is_pdf and len(page_text) >= _MIN_TEXT_CHARS:
                logger.info(
                    "[pag {}] PyMuPDF: {} chars extraídos (sem IA de visão)",
                    page_num,
                    len(page_text),
                )
                response = page_text

                # Descreve imagens embutidas via IA (apenas elas, não a página)
                if page_images:
                    image_prompt = (
                        "Forneça uma audiodescrição curta e objetiva desta "
                        "imagem, em português, para ser inserida em documento "
                        "acessível. Use o formato: [Descrição: ...]"
                    )
                    descriptions: list[str] = []
                    for img_bytes in page_images[:3]:
                        try:
                            desc = await opencode_client.send_message(
                                text=image_prompt,
                                images=[img_bytes],
                            )
                            if desc.strip():
                                descriptions.append(desc.strip())
                        except Exception as err:
                            logger.warning(
                                "[pag {}] Falha ao descrever imagem: {}",
                                page_num,
                                err,
                            )
                    if descriptions:
                        response += "\n" + "\n".join(descriptions)

                await set_cache(page_path, response, page_cache_key)

            else:
                # ----------------------------------------------------------
                # Página sem texto (escaneada) ou imagem direta → IA de visão
                # ----------------------------------------------------------
                try:
                    if is_pdf:
                        logger.debug(
                            "[pag {}] convert_pdf_to_png: {}",
                            page_num,
                            page_path,
                        )
                        png_bytes = convert_pdf_to_png(
                            page_path,
                            settings.pdf_split_dpi,
                        )
                        logger.debug(
                            "[pag {}] PNG gerado: {} bytes",
                            page_num,
                            len(png_bytes),
                        )
                    else:
                        logger.debug(
                            "[pag {}] lendo imagem: {}",
                            page_num,
                            page_path,
                        )
                        with open(page_path, "rb") as file_handle:
                            raw_bytes = file_handle.read()
                        logger.debug(
                            "[pag {}] imagem lida: {} bytes",
                            page_num,
                            len(raw_bytes),
                        )
                        png_bytes = raw_bytes

                    logger.debug("[pag {}] comprimindo para JPG...", page_num)
                    jpg_bytes = _compress_to_jpg(png_bytes)
                    logger.debug(
                        "[pag {}] aplicando melhoria de imagem (OpenCV)...",
                        page_num,
                    )
                    jpg_bytes = enhance_image_for_ocr(jpg_bytes)
                    logger.debug(
                        "[pag {}] JPG final: {} bytes",
                        page_num,
                        len(jpg_bytes),
                    )

                    logger.info(
                        "Enviando pagina {} para IA de visão ({} bytes)",
                        page_num,
                        len(jpg_bytes),
                    )

                    page_prompt = _page_prompt(
                        system_prompt,
                        total_pages,
                        page_num,
                        is_pdf,
                    )

                    logger.debug(
                        "[pag {}] chamando opencode_client.send_message()",
                        page_num,
                    )
                    response = await opencode_client.send_message(
                        text=page_prompt,
                        images=[jpg_bytes],
                    )
                    logger.debug(
                        "[pag {}] resposta recebida: {} chars",
                        page_num,
                        len(response),
                    )

                    await set_cache(page_path, response, page_cache_key)

                except UnicodeDecodeError as error:
                    import traceback

                    tb = traceback.format_exc()
                    logger.critical(
                        "[pag {}] UnicodeDecodeError: {} | Traceback:\n{}",
                        page_num,
                        error,
                        tb,
                    )
                    raise
                except Exception as error:
                    import traceback

                    tb = traceback.format_exc()
                    logger.critical(
                        "[pag {}] Erro inesperado: tipo={} | msg={} | "
                        "Traceback:\n{}",
                        page_num,
                        type(error).__name__,
                        error,
                        tb,
                    )
                    raise

            if not response.strip():
                logger.warning("Resposta vazia para pagina {}", page_num)
                response = (
                    f"[Pagina {page_num}: resposta vazia do modelo]"
                )

            output_file = tmpdir / f"imagen{page_num:03d}.txt"
            output_file.write_text(response, encoding="utf-8")
            logger.info(
                "Resposta da pagina {} salva em {}",
                page_num,
                output_file.name,
            )

            results.append(response)
            page_payloads.append(
                {
                    "page_number": page_num,
                    "file_path": str(page_path),
                    "text": response,
                    "blocks": parse_text_to_blocks(response),
                    "cached": False,
                }
            )

        texto_final = "\n\n".join(
            f"=== Pagina {i + 1} ===\n{response}"
            for i, response in enumerate(results)
        )

        logger.info(
            "AgenteUnico: {} paginas processadas, {} chars no total",
            total_pages,
            len(texto_final),
        )

        if structured_output:
            return {
                "text": texto_final,
                "pages": page_payloads,
                "page_count": total_pages,
                "mode": effective_mode,
                "source_path": str(file_path),
            }

        return texto_final
