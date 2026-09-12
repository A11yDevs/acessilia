"""Agno Workflow implementation for accessible documentary pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Coroutine

from agno.workflow import Workflow
from agno.workflow.step import Step, StepInput, StepOutput

from backend.agents.data_agent import DataAgent
from backend.agents.editor_agent import EditorAgent
from backend.agents.reader_agent import ReaderAgent
from backend.agents.types import RegionTask
from backend.agents.vision_agent import VisionAgent
from backend.i18n import t
from backend.log_messages import (
    LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE,
    LOG_ORCHESTRATOR_PAGE_CACHE_SKIP,
    LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED,
    LOG_ORCHESTRATOR_TASK_FAILED,
    LOG_ORCHESTRATOR_WAITING_TASKS,
    LOG_ORCHESTRATOR_WORKFLOW_START,
    LOG_ORCHESTRATOR_WORKFLOW_SUMMARY,
)
from backend.pipeline.structure_parser import parse_text_to_blocks
from backend.services.cache import get_cached, options_cache_key, set_cache
from backend.stage_messages import (
    STAGE_PREPARING_IMAGE,
    STAGE_PROCESSING_PAGE,
    STAGE_SPLITTING_PDF_PAGES,
)
from backend.tools.logger import logger
from backend.tools.prompt_tools import load_system_prompt


class AccessibilityWorkflow:
    """Document-level Agno Workflow orchestrating accessible document processing."""

    def __init__(self, mode: str = "medio"):
        self.mode = mode
        self.reader = ReaderAgent()
        self.vision = VisionAgent(mode=mode)
        self.data = DataAgent()
        self.editor = EditorAgent()
        self._reader_lock = asyncio.Lock()
        self._workflow: Workflow | None = None

    @property
    def workflow(self) -> Workflow:
        if getattr(self, "_workflow", None) is None:
            self._workflow = Workflow(
                name="accessibility_document_workflow",
                description="Transforms documents into accessible text using Reader, Dispatch, and Editor steps",
                steps=[
                    Step(name="ReaderAgent", executor=self._step_reader),
                    Step(name="DispatchAgent", executor=self._step_dispatch),
                    Step(name="EditorAgent", executor=self._step_editor),
                ],
            )
        return self._workflow

    @workflow.setter
    def workflow(self, val: Workflow) -> None:
        self._workflow = val

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
        """Runs the document workflow and returns the accessible output."""
        effective_mode = mode or self.mode

        run_input = {
            "file_path": file_path,
            "tmpdir": tmpdir,
            "status_callback": status_callback,
            "mode": effective_mode,
            "custom_prompt": custom_prompt,
            "thinking_mode": thinking_mode,
        }

        run_output = await self.workflow.arun(input=run_input)
        if run_output and run_output.step_results:
            for step_res in run_output.step_results:
                if not step_res.success and step_res.error:
                    raise RuntimeError(step_res.error)
        if not run_output or not isinstance(run_output.content, dict):
            raise RuntimeError("Workflow failed to produce structured document output")

        data: dict[str, Any] = run_output.content
        if structured_output:
            return data
        return str(data.get("text", ""))

    # ── Workflow Steps ──

    async def _step_reader(self, step_input: StepInput) -> StepOutput:
        """Step 1: Splits document into pages and extracts structural region tasks."""
        ctx = step_input.input if isinstance(step_input.input, dict) else {}
        file_path = Path(ctx["file_path"])
        tmpdir = Path(ctx["tmpdir"])
        status_callback = ctx.get("status_callback")
        effective_mode = ctx.get("mode") or self.mode
        custom_prompt = ctx.get("custom_prompt")
        thinking_mode = ctx.get("thinking_mode", False)

        is_pdf = file_path.suffix.lower() == ".pdf"
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
            return StepOutput(
                content={},
                success=False,
                error="No pages could be generated from the source file",
                stop=True,
            )

        reader_name = getattr(getattr(self.reader, "structurer", None), "name", "default")
        logger.info(
            t(LOG_ORCHESTRATOR_WORKFLOW_START).format(
                page_count=total_pages,
                file_name=file_path.name,
                reader=reader_name,
                mode=effective_mode,
            )
        )

        pages: list[dict[str, Any]] = []
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
            cached_page = await get_cached(page_path, page_cache_key, ttl=86400)
            if cached_page:
                logger.info(t(LOG_ORCHESTRATOR_PAGE_CACHE_SKIP).format(page_num=page_num))
                pages.append({
                    "page_num": page_num,
                    "page_path": page_path,
                    "cached": True,
                    "cached_text": cached_page,
                    "cache_key": page_cache_key,
                    "tasks": [],
                })
                continue

            async with self._reader_lock:
                tasks = await asyncio.to_thread(
                    self.reader.analyse_page,
                    page_path,
                    page_num,
                    total_pages,
                    is_pdf,
                )

            pages.append({
                "page_num": page_num,
                "page_path": page_path,
                "cached": False,
                "cache_key": page_cache_key,
                "tasks": tasks,
            })

        return StepOutput(
            content={
                **ctx,
                "pages": pages,
                "total_pages": total_pages,
                "is_pdf": is_pdf,
            },
            success=True,
        )

    async def _step_dispatch(self, step_input: StepInput) -> StepOutput:
        """Step 2: Dispatches multimodal tasks in parallel via VisionAgent and DataAgent."""
        data = step_input.previous_step_content
        if not isinstance(data, dict):
            data = step_input.input if isinstance(step_input.input, dict) else {}

        pages = data.get("pages", [])
        total_pages = data.get("total_pages", len(pages))
        effective_mode = data.get("mode") or self.mode
        custom_prompt = data.get("custom_prompt")
        thinking_mode = data.get("thinking_mode", False)

        dispatch_prompt = custom_prompt
        if thinking_mode:
            base_prompt = custom_prompt or load_system_prompt(effective_mode)
            dispatch_prompt = "<|think|>\n" + base_prompt

        results_by_page: dict[int, dict[int, str]] = {}
        for page_info in pages:
            if page_info.get("cached"):
                continue
            page_num = page_info["page_num"]
            tasks = page_info.get("tasks", [])
            agent_results = await self._dispatch_tasks(
                tasks,
                page_num,
                total_pages,
                effective_mode,
                dispatch_prompt,
            )
            results_by_page[page_num] = agent_results

        return StepOutput(
            content={
                **data,
                "agent_results": results_by_page,
            },
            success=True,
        )

    async def _step_editor(self, step_input: StepInput) -> StepOutput:
        """Step 3: Consolidates page tasks into accessible markdown and formats document."""
        data = step_input.previous_step_content
        if not isinstance(data, dict):
            data = step_input.input if isinstance(step_input.input, dict) else {}

        pages = data.get("pages", [])
        total_pages = data.get("total_pages", len(pages))
        agent_results = data.get("agent_results", {})
        tmpdir = Path(data.get("tmpdir", "."))
        file_path = Path(data.get("file_path", "document"))
        effective_mode = data.get("mode") or self.mode

        results: list[str] = []
        page_payloads: list[dict[str, Any]] = []

        for page_info in pages:
            page_num = page_info["page_num"]
            page_path = page_info["page_path"]

            if page_info.get("cached"):
                cached_page = page_info["cached_text"]
                results.append(cached_page)
                page_payloads.append({
                    "page_number": page_num,
                    "file_path": str(page_path),
                    "text": cached_page,
                    "blocks": parse_text_to_blocks(cached_page),
                    "cached": True,
                })
                continue

            tasks = page_info.get("tasks", [])
            page_results = agent_results.get(page_num, {})
            page_text = self.editor.consolidate_page(tasks, page_results)

            if not page_text.strip():
                logger.warning(t(LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE).format(page_num=page_num))
                page_text = f"[Pagina {page_num}: resposta vazia do modelo]"

            await set_cache(page_path, page_text, page_info["cache_key"])

            output_file = tmpdir / f"imagen{page_num:03d}.txt"
            output_file.write_text(page_text, encoding="utf-8")
            logger.info(
                t(LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED).format(
                    page_num=page_num, file_name=output_file.name
                )
            )

            results.append(page_text)
            page_payloads.append({
                "page_number": page_num,
                "file_path": str(page_path),
                "text": page_text,
                "blocks": parse_text_to_blocks(page_text),
                "cached": False,
            })

        texto_final = "\n\n".join(
            f"=== Pagina {i + 1} ===\n{response}" for i, response in enumerate(results)
        )

        logger.info(
            t(LOG_ORCHESTRATOR_WORKFLOW_SUMMARY).format(
                total_pages=total_pages, total_chars=len(texto_final)
            )
        )

        return StepOutput(
            content={
                "text": texto_final,
                "pages": page_payloads,
                "page_count": total_pages,
                "mode": effective_mode,
                "source_path": str(file_path),
            },
            success=True,
        )

    # ── Task Dispatcher ──

    async def _dispatch_tasks(
        self,
        tasks: list[RegionTask],
        page_num: int,
        total_pages: int,
        mode: str,
        custom_prompt: str | None,
    ) -> dict[int, str]:
        """Dispatches vision and data processing tasks in parallel."""
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


DocumentWorkflow = AccessibilityWorkflow
AccessibilityOrchestrator = AccessibilityWorkflow
