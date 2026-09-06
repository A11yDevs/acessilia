"""ReaderAgent – Leitura estrutural e classificação de regiões de páginas."""

from pathlib import Path

import fitz

from backend.config.settings import settings
from backend.tools.region_classifier import (
    classify_region,
    formula_already_extracted,
    region_has_markers,
    region_needs_vision,
)
from backend.tools.region_extractor import Region
from backend.tools.logger import logger
from backend.tools.pdf_splitter import split_pdf

from backend.agents.types import RegionTask
from backend.tools.formula_tools import (
    ensure_math_delimiters,
    try_extract_formula_locally,
)
from backend.tools.text_tools import apply_marker, content_fingerprint, overlaps_clean
from backend.tools.image_tools import crop_region_image, prepare_image_bytes, render_full_page
from backend.tools.structurer import get_structurer as get_structurer_instance


class ReaderAgent:
    """Analisa páginas e gera tarefas tipadas para os demais agentes."""

    def __init__(self):
        self.structurer = get_structurer_instance()

    def split_file(self, file_path: Path, tmpdir: Path) -> list[Path]:
        """Divide PDF em páginas individuais; retorna [file_path] para imagens."""
        is_pdf = file_path.suffix.lower() == ".pdf"
        if is_pdf:
            return split_pdf(file_path, tmpdir, settings.max_pages)
        return [file_path]

    def analyse_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        is_pdf: bool,
    ) -> list[RegionTask]:
        """Analisa uma página e retorna uma lista de RegionTasks."""

        if not is_pdf:
            return self._analyse_image_page(page_path, page_num, total_pages)

        return self._analyse_pdf_page(page_path, page_num, total_pages)

    # ── PDF ──

    def _analyse_pdf_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
    ) -> list[RegionTask]:
        doc = fitz.open(page_path)
        try:
            page = doc[0]
            regions = self.structurer.extract_page_regions(page)
        finally:
            doc.close()

        if not regions:
            return []

        logger.info(
            "[pag {}] Extraidas {} regioes na pagina (structurer={})",
            page_num,
            len(regions),
            self.structurer.name,
        )

        # Verifica se todas as regiões são texto limpo (sem necessidade de visão)
        all_text_clean = True
        for r in regions:
            classification = classify_region(r)
            if classification != "text_clean" and classification != "ignore":
                all_text_clean = False
                break

        if all_text_clean:
            return self._extract_clean_text_tasks(regions, page_num)

        return self._extract_mixed_tasks(page_path, regions, page_num, total_pages)

    def _extract_clean_text_tasks(
        self,
        regions: list[Region],
        page_num: int,
    ) -> list[RegionTask]:
        """Gera tarefas para regiões puramente textuais (sem visão)."""
        tasks: list[RegionTask] = []
        clean_fps: set[int] = set()

        for region in regions:
            classification = classify_region(region)

            if classification == "text_clean" and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in clean_fps:
                    clean_fps.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=region.text,
                        region=region,
                        page_num=page_num,
                    ))
            elif region_has_markers(classification) and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in clean_fps:
                    clean_fps.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=apply_marker(region.text, classification, region),
                        region=region,
                        page_num=page_num,
                    ))

        if tasks:
            logger.info(
                "[pag {}] {} regioes de texto limpo (sem IA de visao)",
                page_num,
                len(tasks),
            )

        return tasks

    def _extract_mixed_tasks(
        self,
        page_path: Path,
        regions: list[Region],
        page_num: int,
        total_pages: int,
    ) -> list[RegionTask]:
        """Gera tarefas mistas: texto limpo direto + regiões que precisam de visão."""
        tasks: list[RegionTask] = []
        clean_bboxes: list[tuple[float, float, float, float]] = []
        content_fingerprints: set[int] = set()
        vision_count = 0

        for region in regions:
            classification = classify_region(region)

            if classification == "ignore":
                continue

            # Texto limpo → vai direto para o EditorAgent
            if classification == "text_clean" and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=region.text,
                        region=region,
                        page_num=page_num,
                    ))
                    clean_bboxes.append(region.bbox)
                continue

            # Regiões com marcadores mas que possuem texto limpo
            if region_has_markers(classification) and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=apply_marker(region.text, classification, region),
                        region=region,
                        page_num=page_num,
                    ))
                    clean_bboxes.append(region.bbox)
                continue

            # Fórmula com LaTeX já extraído pelo Docling (CodeFormula) → editor direto
            if classification == "formula" and formula_already_extracted(region):
                latex = ensure_math_delimiters(region.text)
                fp = content_fingerprint(latex)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    logger.info(
                        "[pag {}] Formula ja enriquecida pelo Docling (sem LLM)",
                        page_num,
                    )
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=latex,
                        region=region,
                        page_num=page_num,
                    ))
                    clean_bboxes.append(region.bbox)
                continue

            # Regiões que precisam de visão
            if region_needs_vision(classification):
                if classification in ("unknown", "text_scanned") and overlaps_clean(
                    region.bbox, clean_bboxes
                ):
                    if region.text.strip():
                        fp = content_fingerprint(region.text)
                        if fp not in content_fingerprints:
                            content_fingerprints.add(fp)
                            tasks.append(RegionTask(
                                agent_target="editor",
                                classification=classification,
                                text=region.text,
                                region=region,
                                page_num=page_num,
                            ))
                    continue

                vision_count += 1

                # Recorta a imagem da região para enviar ao agente de visão
                image_bytes = crop_region_image(
                    self.structurer, page_path, region,
                )

                # Cascata local: imagem que na verdade é fórmula → OCR + CodeFormula
                if (
                    classification == "embedded_image"
                    and settings.formula_image_cascade
                ):
                    latex = try_extract_formula_locally(image_bytes)
                    if latex:
                        latex = ensure_math_delimiters(latex)
                        vision_count -= 1
                        fp = content_fingerprint(latex)
                        if fp in content_fingerprints:
                            continue
                        content_fingerprints.add(fp)
                        logger.info(
                            "[pag {}] Imagem identificada como formula pela "
                            "cascata local (sem LLM)",
                            page_num,
                        )
                        tasks.append(RegionTask(
                            agent_target="editor",
                            classification="formula",
                            text=latex,
                            region=region,
                            page_num=page_num,
                        ))
                        continue

                # Determina qual agente processar a tarefa
                if classification in ("table",):
                    target = "data"
                elif classification in ("formula",):
                    target = "data"
                elif classification in ("embedded_image",):
                    target = "vision"
                else:
                    target = "vision"

                logger.info(
                    "[pag {}] Regiao {} - tipo={}, bbox={}, target={}",
                    page_num,
                    len(tasks) + 1,
                    classification,
                    region.bbox,
                    target,
                )

                tasks.append(RegionTask(
                    agent_target=target,
                    classification=classification,
                    text=region.text,
                    image_bytes=image_bytes,
                    region=region,
                    page_num=page_num,
                ))

        if not tasks:
            # Fallback: envia a página inteira para o VisionAgent
            logger.warning(
                "[pag {}] Nenhum texto extraido por regioes, "
                "fallback para pagina inteira",
                page_num,
            )
            image_bytes = render_full_page(page_path)
            tasks.append(RegionTask(
                agent_target="vision",
                classification="full_page_fallback",
                image_bytes=image_bytes,
                page_num=page_num,
            ))

        logger.info(
            "[pag {}] {} tarefas ({} texto, {} visao)",
            page_num,
            len(tasks),
            len(tasks) - vision_count,
            vision_count,
        )

        return tasks

    # ── Imagem ──

    def _analyse_image_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
    ) -> list[RegionTask]:
        """Para arquivos de imagem, gera uma única tarefa de visão."""
        logger.debug("[pag {}] lendo imagem: {}", page_num, page_path)
        with open(page_path, "rb") as file_handle:
            raw_bytes = file_handle.read()

        jpg_bytes = prepare_image_bytes(raw_bytes)

        return [RegionTask(
            agent_target="vision",
            classification="full_page_image",
            image_bytes=jpg_bytes,
            page_num=page_num,
        )]
