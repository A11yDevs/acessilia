import datetime
import json
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.agents.orchestrator import AccessibilityOrchestrator
from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
from backend.agents.state_manager import TaskCancelledError, state_manager
from backend.services.cache import get_cached, options_cache_key, set_cache
from backend.services.history_service import (
    finalizar_conversao,
    limpar_orfas,
    registrar_conversao,
)
from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import (
    LOG_CANONICAL_JSON_SAVE_FAILED,
    LOG_CACHE_HIT,
    LOG_ORCHESTRATOR_EMPTY_AGENT_RESPONSE,
    LOG_PIPELINE_ERROR,
    LOG_STRUCTURER_FALLBACK_PYMUPDF,
    LOG_TASK_CANCELLED_BY_USER,
)
from backend.stage_messages import (
    STAGE_ANALYZING_FILE,
    STAGE_CANCELLED_BY_USER,
    STAGE_PROCESSING_FAILED_LABEL,
    STAGE_PROCESSING_FINISHED,
    STAGE_PROCESSING_WITH_AI,
    STAGE_PREPARING_FILE,
)
from backend.tools.logger import logger
from backend.tools.structurer import DOCLING_AVAILABLE
from backend.tools.text_processor import merge_broken_paragraphs
from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.verbosity_manager import verbosity_for_mode


def _normalized_engine() -> str:
    engine = settings.pipeline_engine.strip().lower()
    if engine in {"pddl", "pmv"}:
        return "pddl"
    return "legacy"


def _resolved_structurer() -> str:
    structurer = settings.structurer.strip().lower()
    if structurer == "docling" and not DOCLING_AVAILABLE:
        logger.warning(t(LOG_STRUCTURER_FALLBACK_PYMUPDF))
        return "pymupdf"
    if structurer == "toolbox":
        logger.info("STRUCTURER=toolbox: usando Acessilia Toolbox remota")
    return structurer


def _build_orchestrator():
    if _normalized_engine() == "pddl":
        structurer = _resolved_structurer()
        fast_downward = (
            Path(settings.pddl_fast_downward).expanduser()
            if settings.pddl_fast_downward.strip()
            else None
        )
        alias = settings.pddl_fast_downward_alias.strip() or None
        return PddlAccessibilityOrchestrator(
            planner_backend=settings.pddl_planner_backend,
            preferred_plan=settings.pddl_preferred_plan,
            execute_dry_run=settings.pddl_execute_dry_run,
            fast_downward=fast_downward,
            fast_downward_alias=alias,
            fast_downward_search=settings.pddl_fast_downward_search,
            enable_ocr=structurer == "docling",
            extractor_backend=structurer,
        )
    return AccessibilityOrchestrator()


agente = _build_orchestrator()


def _cache_version(
    mode: str = "normal",
    custom_prompt: str | None = None,
    thinking_mode: bool = False,
) -> str:
    engine = _normalized_engine()
    structurer = _resolved_structurer()
    return options_cache_key(
        f"{settings.ai_client}-{engine}-{structurer}-v2",
        mode=mode,
        custom_prompt=custom_prompt or "",
        thinking_mode=thinking_mode,
    )


def _limpar_tarefas_orfas():
    limpar_orfas()


_limpar_tarefas_orfas()


def _salvar_json_canonico(canonical_document: dict, source_name: str) -> None:
    try:
        base = Path("var") / "output" / "canonical"
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_dir = base / ts
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(source_name).stem
        path = out_dir / f"{stem}.json"
        path.write_text(
            json.dumps(canonical_document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(t(LOG_CANONICAL_JSON_SAVE_FAILED).format(error=e))


def _payload_for_source(payload: Any, file_path: Path) -> Any:
    if not isinstance(payload, dict):
        return payload

    current = {**payload, "source_path": str(file_path)}
    pages = payload.get("pages")
    if isinstance(pages, list):
        current_pages = []
        for index, page in enumerate(pages):
            if not isinstance(page, dict):
                current_pages.append(page)
                continue
            page_path = (
                file_path.parent / f"pagina_{index + 1:03d}.pdf"
                if file_path.suffix.lower() == ".pdf"
                else file_path
            )
            current_pages.append({**page, "file_path": str(page_path)})
        current["pages"] = current_pages
    return current


def _canonical_details(payload: Any) -> tuple[dict[str, Any] | None, list[str] | None]:
    if not isinstance(payload, dict):
        return None, None
    metadata = payload.get("canonical_metadata")
    warnings = payload.get("technical_warnings")
    return (
        metadata if isinstance(metadata, dict) else None,
        [str(item) for item in warnings] if isinstance(warnings, list) else None,
    )


async def process(
    file_path: Path,
    status_callback: Callable[[str], Coroutine] | None = None,
    mode: str = "normal",
    custom_prompt: str | None = None,
    thinking_mode: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    external_task_id = task_id is not None
    if task_id is None:
        task_id = state_manager.criar_tarefa(file_path)
    elif state_manager.obter(task_id) is None:
        state_manager.criar_tarefa(file_path, task_id=task_id)
    state_manager.verificar_cancelamento(task_id)
    inicio = time.time()
    await registrar_conversao(
        task_id=task_id,
        arquivo=file_path.name,
        extensao=file_path.suffix,
        tamanho_bytes=file_path.stat().st_size,
        modo=mode,
    )

    try:
        cache_variant = _cache_version(mode, custom_prompt, thinking_mode)
        cached = await get_cached(file_path, cache_variant)
        if cached is not None:
            logger.info("Cache hit para {}", file_path.name)
            cached = _payload_for_source(cached, file_path)
            canonical_metadata, technical_warnings = _canonical_details(cached)
            canonical_document = build_canonical_document(
                cached,
                title=file_path.stem,
                language="pt-BR",
                verbosity=verbosity_for_mode(mode),
                source_name=file_path.name,
                source_path=str(file_path),
                audience=["reader"],
                metadata=canonical_metadata,
                technical_warnings=technical_warnings,
            )
            if not external_task_id:
                state_manager.finalizar(
                    task_id,
                    json.dumps(canonical_document, ensure_ascii=False),
                )
                await finalizar_conversao(
                    task_id=task_id,
                    status="done",
                    pipeline=f"{settings.ai_client}-{_normalized_engine()}",
                    resultado_resumo=canonical_document["title"][:200],
                    tempo_segundos=time.time() - inicio,
                )
            if status_callback:
                await status_callback("✅ Processamento finalizado com sucesso!")
            return canonical_document

        state_manager.atualizar(
            task_id,
            etapa=t(STAGE_PREPARING_FILE),
            progresso=0.1,
        )
        state_manager.verificar_cancelamento(task_id)

        if status_callback:
            await status_callback(t(STAGE_ANALYZING_FILE))

        state_manager.atualizar(
            task_id,
            etapa=t(STAGE_PROCESSING_WITH_AI),
            progresso=0.3,
        )
        state_manager.verificar_cancelamento(task_id)

        resultado = await agente.executar(
            file_path,
            file_path.parent,
            status_callback,
            mode=mode,
            structured_output=True,
            custom_prompt=custom_prompt,
            thinking_mode=thinking_mode,
        )

        canonical_metadata: dict[str, Any] | None = None
        technical_warnings: list[str] | None = None
        if isinstance(resultado, dict):
            raw_text = resultado["text"]
            payload_metadata = resultado.get("canonical_metadata")
            if isinstance(payload_metadata, dict):
                canonical_metadata = payload_metadata
            payload_warnings = resultado.get("technical_warnings")
            if isinstance(payload_warnings, list):
                technical_warnings = [str(item) for item in payload_warnings]
        else:
            raw_text = resultado

        raw_text = merge_broken_paragraphs(raw_text)

        processed_result: str | dict[str, Any]
        if isinstance(resultado, dict):
            processed_result = {**resultado, "text": raw_text}
        else:
            processed_result = raw_text

        state_manager.verificar_cancelamento(task_id)
        if not raw_text.strip():
            raise RuntimeError(t(LOG_ORCHESTRATOR_EMPTY_AGENT_RESPONSE))

        canonical_document = build_canonical_document(
            processed_result,
            title=file_path.stem,
            language="pt-BR",
            verbosity=verbosity_for_mode(mode),
            source_name=file_path.name,
            source_path=str(file_path),
            audience=["reader"],
            metadata=canonical_metadata,
            technical_warnings=technical_warnings,
        )

        await set_cache(file_path, processed_result, cache_variant)
        _salvar_json_canonico(canonical_document, file_path.name)

        if not external_task_id:
            state_manager.finalizar(
                task_id,
                json.dumps(canonical_document, ensure_ascii=False),
            )
            await finalizar_conversao(
                task_id=task_id,
                status="done",
                pipeline=f"{settings.ai_client}-{_normalized_engine()}",
                resultado_resumo=canonical_document["title"][:200],
                tempo_segundos=time.time() - inicio,
            )

        if status_callback:
            await status_callback(t(STAGE_PROCESSING_FINISHED))
        return canonical_document

    except TaskCancelledError:
        logger.info(t(LOG_TASK_CANCELLED_BY_USER).format(task_id=task_id))
        await finalizar_conversao(
            task_id=task_id,
            status="cancelled",
            erro=t(STAGE_CANCELLED_BY_USER),
            tempo_segundos=time.time() - inicio,
        )
        raise

    except Exception as e:
        logger.error(t(LOG_PIPELINE_ERROR).format(error_type=type(e).__name__, error=e))
        state_manager.errar(task_id, str(e))

        await finalizar_conversao(
            task_id=task_id,
            status="error",
            erro=str(e),
            tempo_segundos=time.time() - inicio,
        )

        if status_callback:
            await status_callback(t(STAGE_PROCESSING_FAILED_LABEL))
            await status_callback("❌ Nao foi possivel processar o arquivo.")
        raise
