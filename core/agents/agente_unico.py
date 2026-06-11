import io
from pathlib import Path
from typing import Any, Callable, Coroutine

import fitz
from PIL import Image

from config.settings import settings

if settings.ai_client == "openrouter":
    from core.ai.openrouter import client as ai_client
else:
    from core.ai.ollama import client as ai_client

from core.region_classifier import (
    classify_region,
    region_has_markers,
    region_needs_vision,
    region_prompt_key,
)
from core.region_extractor import Region
from core.services.cache import get_cached, set_cache
from core.structurer import BaseStructurer, get_structurer
from core.utils.image_converter import convert_pdf_to_png
from core.utils.image_enhancer import enhance_image_for_ocr, resize_image
from core.utils.logger import logger
from core.utils.pdf_splitter import split_pdf
from pipeline.structure_parser import parse_text_to_blocks

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "interfaces" / "telegram" / "prompts"

MODE_MAP = {
    "detalhado": "detalhado.txt",
    "medio": "medio.txt",
    "normal": "medio.txt",
    "baixo": "baixo.txt",
    "ocr": "ocr.txt",
}

REGION_PROMPT_MAP = {
    "regiao_imagem": "regiao_imagem.txt",
    "regiao_texto_escaneado": "regiao_texto_escaneado.txt",
    "regiao_tabela": "regiao_tabela.txt",
    "regiao_formula": "regiao_formula.txt",
}

REGION_MARKERS: dict[str, tuple[str, str]] = {
    "code_block": ("Início de código-fonte:", "Fim de código-fonte"),
    "list_block": ("Início de lista:", "Fim de lista"),
    "callout_box": ("Início de box:", "Fim de box"),
    "embedded_image": ("Início de imagem:", "Fim de imagem"),
}

CALLOUT_LABEL_MAP: dict[str, str] = {
    "note": "nota",
    "quote": "citação",
    "sidebar": "barra lateral",
    "warning": "aviso",
    "tip": "dica",
    "important": "importante",
}

def _apply_marker(text: str, classification: str, region: Region) -> str:
    markers = REGION_MARKERS.get(classification)
    if not markers:
        return text
    start, end = markers
    lab = region.metadata.get("docling_label", "")
    custom = CALLOUT_LABEL_MAP.get(lab)
    if custom:
        start = f"Início de {custom}:"
        end = f"Fim de {custom}"
    return f"{start}\n{text}\n{end}"


def _overlaps_clean(
    bbox: tuple[float, float, float, float],
    clean_bboxes: list[tuple[float, float, float, float]],
    threshold: float = 0.3,
) -> bool:
    x0, y0, x1, y1 = bbox
    area = max((x1 - x0) * (y1 - y0), 1)
    for cb in clean_bboxes:
        ox0 = max(x0, cb[0])
        oy0 = max(y0, cb[1])
        ox1 = min(x1, cb[2])
        oy1 = min(y1, cb[3])
        if ox0 < ox1 and oy0 < oy1:
            overlap = (ox1 - ox0) * (oy1 - oy0)
            if overlap / area >= threshold:
                return True
    return False


def _content_fingerprint(text: str) -> int:
    clean = " ".join(text.lower().split())
    return hash(clean)


_structurer: BaseStructurer | None = None


def _get_structurer() -> BaseStructurer:
    global _structurer
    if _structurer is None:
        _structurer = get_structurer()
    return _structurer


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


def _load_region_prompt(region_type: str) -> str:
    filename = REGION_PROMPT_MAP.get(region_type)
    if not filename:
        return ""
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return ""


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
    def __init__(self, mode: str = "medio"):
        self.mode = mode
        self.system_prompt = _load_system_prompt(mode)
        self.structurer = _get_structurer()

    async def executar(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine] | None = None,
        mode: str | None = None,
        structured_output: bool = False,
        custom_prompt: str | None = None,
        thinking_mode: bool = False,
    ) -> str | dict[str, Any]:
        effective_mode = mode or self.mode
        if custom_prompt:
            system_prompt = custom_prompt
        else:
            system_prompt = _load_system_prompt(effective_mode)
        if thinking_mode:
            system_prompt = "<|think|>\n" + system_prompt
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
            "Processando {} pagina(s) para {} com structurer={}",
            total_pages,
            file_path.name,
            self.structurer.name,
        )

        results: list[str] = []
        page_payloads: list[dict[str, Any]] = []

        for index, page_path in enumerate(page_pdfs):
            page_num = index + 1
            if status_callback:
                label = f"📷 Processando pagina {page_num} de {total_pages}..."
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

            response = await self._process_page(
                page_path, page_num, total_pages, is_pdf,
                system_prompt, effective_mode, status_callback,
            )

            if not response.strip():
                logger.warning("Resposta vazia para pagina {}", page_num)
                response = f"[Pagina {page_num}: resposta vazia do modelo]"

            await set_cache(page_path, response, page_cache_key)

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

    async def _process_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        is_pdf: bool,
        system_prompt: str,
        effective_mode: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        if is_pdf:
            return await self._process_pdf_page(
                page_path, page_num, total_pages, system_prompt,
                effective_mode, status_callback,
            )

        return await self._process_image_page(
            page_path, page_num, total_pages, system_prompt, status_callback,
        )

    async def _process_pdf_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        effective_mode: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        doc = fitz.open(page_path)
        try:
            page = doc[0]
            regions = self.structurer.extract_page_regions(page)
        finally:
            doc.close()

        if not regions:
            return ""

        logger.info(
            "[pag {}] Extraidas {} regioes na pagina (structurer={})",
            page_num,
            len(regions),
            self.structurer.name,
        )

        all_text_clean = True
        for r in regions:
            classification = classify_region(r)
            if classification != "text_clean" and classification != "ignore":
                all_text_clean = False
                break

        if all_text_clean:
            text_parts: list[str] = []
            clean_fps: set[int] = set()
            for region in regions:
                classification = classify_region(region)
                if classification == "text_clean" and region.text.strip():
                    fp = _content_fingerprint(region.text)
                    if fp not in clean_fps:
                        clean_fps.add(fp)
                        text_parts.append(region.text)
                elif region_has_markers(classification) and region.text.strip():
                    fp = _content_fingerprint(region.text)
                    if fp not in clean_fps:
                        clean_fps.add(fp)
                        text_parts.append(_apply_marker(region.text, classification, region))
            full_text = "\n\n".join(text_parts)

            if len(full_text) >= 20:
                logger.info(
                    "[pag {}] {} regioes de texto limpo (sem IA de visao)",
                    page_num,
                    len(text_parts),
                )
                return full_text

        return await self._process_with_vision_by_regions(
            page_path, page_num, total_pages, system_prompt, status_callback,
        )

    async def _process_with_vision_by_regions(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        doc = fitz.open(page_path)
        try:
            page = doc[0]
            regions = self.structurer.extract_page_regions(page)
        finally:
            doc.close()

        text_parts: list[str] = []
        vision_count = 0
        clean_bboxes: list[tuple[float, float, float, float]] = []
        content_fingerprints: set[int] = set()

        for region in regions:
            classification = classify_region(region)

            if classification == "ignore":
                continue

            if classification == "text_clean" and region.text.strip():
                fp = _content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    text_parts.append(region.text)
                    clean_bboxes.append(region.bbox)
                continue

            if region_has_markers(classification) and region.text.strip():
                fp = _content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    text_parts.append(_apply_marker(region.text, classification, region))
                    clean_bboxes.append(region.bbox)
                continue

            if region_needs_vision(classification):
                if classification in ("unknown", "text_scanned") and _overlaps_clean(
                    region.bbox, clean_bboxes
                ):
                    if region.text.strip():
                        fp = _content_fingerprint(region.text)
                        if fp not in content_fingerprints:
                            content_fingerprints.add(fp)
                            text_parts.append(region.text)
                    continue
                vision_count += 1
                logger.info(
                    "[pag {}] Regiao {} - tipo={}, bbox={}",
                    page_num,
                    len(text_parts) + vision_count,
                    classification,
                    region.bbox,
                )

                region_desc = await self._process_region_with_vision(
                    page_path, region, classification, page_num,
                    total_pages, system_prompt, status_callback,
                )
                if region_desc.strip():
                    fp = _content_fingerprint(region_desc)
                    if fp not in content_fingerprints:
                        content_fingerprints.add(fp)
                        if region_has_markers(classification):
                            region_desc = _apply_marker(region_desc, classification, region)
                        text_parts.append(region_desc)

        if not text_parts:
            logger.warning(
                "[pag {}] Nenhum texto extraido por regioes, "
                "fallback para pagina inteira",
                page_num,
            )
            return await self._fallback_whole_page(
                page_path, page_num, total_pages, system_prompt,
                status_callback,
            )

        logger.info(
            "[pag {}] {} regioes ({}, {} visao sequencial)",
            page_num,
            len(text_parts),
            len(text_parts) - vision_count,
            vision_count,
        )

        return "\n\n".join(text_parts)

    async def _process_region_with_vision(
        self,
        page_path: Path,
        region: Region,
        classification: str,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        prompt_key = region_prompt_key(classification)
        base_prompt = _load_region_prompt(prompt_key)

        if not base_prompt:
            base_prompt = system_prompt

        region_prompt = base_prompt

        try:
            doc = fitz.open(page_path)
            try:
                page = doc[0]
                region_png = self.structurer.crop_region(page, region.bbox, dpi=200)
            finally:
                doc.close()

            jpg_bytes = _compress_to_jpg(region_png)
            jpg_bytes = enhance_image_for_ocr(jpg_bytes)
            jpg_bytes = resize_image(jpg_bytes)

            logger.debug(
                "[pag {}] Enviando regiao para visao ({} bytes, tipo={})",
                page_num,
                len(jpg_bytes),
                classification,
            )

            result = await ai_client.send_message(
                text=region_prompt,
                images=[jpg_bytes],
            )

            return result.strip()

        except Exception as error:
            import traceback
            tb = traceback.format_exc()
            logger.critical(
                "[pag {}] Erro na regiao {}: {} | Traceback:\n{}",
                page_num,
                classification,
                error,
                tb,
            )
            if region.text.strip():
                return region.text
            return ""

    async def _fallback_whole_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        logger.info(
            "[pag {}] Fallback: enviando pagina inteira para IA de visao",
            page_num,
        )

        png_bytes = convert_pdf_to_png(page_path, settings.pdf_split_dpi)
        jpg_bytes = _compress_to_jpg(png_bytes)
        jpg_bytes = enhance_image_for_ocr(jpg_bytes)
        jpg_bytes = resize_image(jpg_bytes)

        prompt = _page_prompt(system_prompt, total_pages, page_num, is_pdf=True)

        result = await ai_client.send_message(
            text=prompt,
            images=[jpg_bytes],
        )

        return result.strip()

    async def _process_image_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        system_prompt: str,
        status_callback: Callable[[str], Coroutine] | None,
    ) -> str:
        logger.debug("[pag {}] lendo imagem: {}", page_num, page_path)
        with open(page_path, "rb") as file_handle:
            raw_bytes = file_handle.read()

        jpg_bytes = _compress_to_jpg(raw_bytes)
        jpg_bytes = enhance_image_for_ocr(jpg_bytes)
        jpg_bytes = resize_image(jpg_bytes)

        logger.info(
            "Enviando pagina {} para IA de visao ({} bytes)",
            page_num,
            len(jpg_bytes),
        )

        prompt = _page_prompt(system_prompt, total_pages, page_num, is_pdf=False)

        result = await ai_client.send_message(
            text=prompt,
            images=[jpg_bytes],
        )

        return result.strip()
