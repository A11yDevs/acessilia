"""Orchestration of documentary-accessibility agents running in an async pipeline."""

import asyncio
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.agents.reader_agent import ReaderAgent
from backend.agents.vision_agent import VisionAgent
from backend.agents.data_agent import DataAgent
from backend.agents.editor_agent import EditorAgent
from backend.agents.types import RegionTask
from backend.services.cache import get_cached, options_cache_key, set_cache
from backend.i18n import t
from backend.log_messages import (
    LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE,
    LOG_ORCHESTRATOR_PAGE_CACHE_SKIP,
    LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED,
    LOG_ORCHESTRATOR_WORKFLOW_START,
    LOG_ORCHESTRATOR_WORKFLOW_SUMMARY,
    LOG_ORCHESTRATOR_WAITING_TASKS,
    LOG_ORCHESTRATOR_TASK_FAILED,
)
from backend.stage_messages import (
    STAGE_PREPARING_IMAGE,
    STAGE_PROCESSING_PAGE,
    STAGE_SPLITTING_PDF_PAGES,
)
from backend.tools.logger import logger
from backend.tools.prompt_tools import load_system_prompt
from backend.pipeline.structure_parser import parse_text_to_blocks

class AccessibilityOrchestrator:
    """Drives the pipeline that performs accessible document processing."""

    def __init__(self, mode: str = "medio"):
        self.mode = mode
        self.reader = ReaderAgent()
        self.vision = VisionAgent(mode=mode)
        self.data = DataAgent()
        self.editor = EditorAgent()
        self._reader_lock = asyncio.Lock()

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
        """Processes the document and produces its corresponding accessible (plain text) version."""
        effective_mode = mode or self.mode
        is_pdf = file_path.suffix.lower() == ".pdf"

        dispatch_prompt = custom_prompt
        if thinking_mode:
            base_prompt = custom_prompt or load_system_prompt(effective_mode)
            dispatch_prompt = "<|think|>\n" + base_prompt

        if is_pdf:
            if status_callback:
                await status_callback(t(STAGE_SPLITTING_PDF_PAGES))
            async with self._reader_lock:
                page_paths = await asyncio.to_thread(
                    self.reader.split_file, file_path, tmpdir
                )
        else:
            if status_callback:
                await status_callback(t(STAGE_PREPARING_IMAGE))
            page_paths = [file_path]

        total_pages = len(page_paths)
        if total_pages == 0:
            raise RuntimeError("No pages could be generated from the source file")

        logger.info(
            t(LOG_ORCHESTRATOR_WORKFLOW_START).format(
                page_count=total_pages,
                file_name=file_path.name,
                reader=self.reader.structurer.name,
                mode=effective_mode,
            )
        )

        results: list[str] = []
        page_payloads: list[dict[str, Any]] = []

        for index, page_path in enumerate(page_paths):
            page_num = index + 1
            if status_callback:
                label = t(STAGE_PROCESSING_PAGE).format(
                    page_num=page_num, total_pages=total_pages
                )
                await status_callback(label)

            page_cache_key = options_cache_key(
                f"page_{page_num}_v2",
                mode=effective_mode,
                custom_prompt=custom_prompt or "",
                thinking_mode=thinking_mode,
            )
            cached_page = await get_cached(
                page_path,
                page_cache_key,
                ttl=86400,
            )
            if cached_page:
                logger.info(
                    t(LOG_ORCHESTRATOR_PAGE_CACHE_SKIP).format(page_num=page_num)
                )
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

            async with self._reader_lock:
                tasks = await asyncio.to_thread(
                    self.reader.analyse_page,
                    page_path, page_num, total_pages, is_pdf,
                )

            agent_results = await self._dispatch_tasks(
                tasks,
                page_num,
                total_pages,
                effective_mode,
                dispatch_prompt,
            )

            page_text = self.editor.consolidate_page(tasks, agent_results)

            if not page_text.strip():
                logger.warning(
                    t(LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE).format(page_num=page_num)
                )
                page_text = f"[Pagina {page_num}: resposta vazia do modelo]"

            await set_cache(page_path, page_text, page_cache_key)

            output_file = tmpdir / f"imagen{page_num:03d}.txt"
            output_file.write_text(page_text, encoding="utf-8")
            logger.info(
                t(LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED).format(
                    page_num=page_num, file_name=output_file.name
                )
            )

            results.append(page_text)
            page_payloads.append(
                {
                    "page_number": page_num,
                    "file_path": str(page_path),
                    "text": page_text,
                    "blocks": parse_text_to_blocks(page_text),
                    "cached": False,
                }
            )

        texto_final = "\n\n".join(
            f"=== Pagina {i + 1} ===\n{response}" for i, response in enumerate(results)
        )

        logger.info(
            t(LOG_ORCHESTRATOR_WORKFLOW_SUMMARY).format(
                total_pages=total_pages, total_chars=len(texto_final)
            )
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

    async def _dispatch_tasks(
        self,
        tasks: list[RegionTask],
        page_num: int,
        total_pages: int,
        mode: str,
        custom_prompt: str | None,
    ) -> dict[int, str]:
        """Despacha tarefas de processamento de imagem em paralelo."""
        results: dict[int, str] = {}
        pending: list[tuple[int, asyncio.Task]] = []

        for idx, task in enumerate(tasks):
            if task.agent_target == "editor":
                continue

            if task.image_bytes is None:
                if task.text.strip():
                    results[idx] = task.text
                continue

            if task.agent_target == "vision":
                coro = self.vision.describe_region(
                    image_bytes=task.image_bytes,
                    classification=task.classification,
                    page_num=page_num,
                    total_pages=total_pages,
                    mode=mode,
                    custom_prompt=custom_prompt,
                )
            elif task.agent_target == "data":
                coro = self.data.process_region(
                    image_bytes=task.image_bytes,
                    classification=task.classification,
                    page_num=page_num,
                    fallback_text=task.text,
                )
            else:
                continue

            async_task = asyncio.create_task(coro)
            pending.append((idx, async_task))

        if pending:
            logger.info(
                t(LOG_ORCHESTRATOR_WAITING_TASKS).format(
                    page_num=page_num,
                    count=len(pending),
                )
            )
            done = await asyncio.gather(
                *(t for _, t in pending),
                return_exceptions=True,
            )
            for (idx, _), result in zip(pending, done):
                if isinstance(result, Exception):
                    logger.error(
                        t(LOG_ORCHESTRATOR_TASK_FAILED).format(
                            page_num=page_num,
                            idx=idx,
                            error=result,
                        )
                    )
                    results[idx] = tasks[idx].text if tasks[idx].text.strip() else ""
                else:
                    results[idx] = result

        return results
