import datetime
import json
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.agents.orchestrator import AccessibilityOrchestrator
from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
from backend.agents.state_manager import TaskCancelledError, state_manager
from backend.observability import record_pipeline_error
from backend.services.cache import get_cached, set_cache
from backend.services.history_service import (
    finalizar_conversao,
    limpar_orfas,
    registrar_conversao,
)
from backend.config.settings import settings
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
        logger.warning(
            "STRUCTURER=docling mas docling nao instalado. Usando PyMuPDF."
        )
        return "pymupdf"
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


def _cache_version() -> str:
    engine = _normalized_engine()
    return f"{settings.ai_client}-{engine}-v1"


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
        logger.warning("Nao foi possivel salvar JSON canonico: {}", e)


async def process(
    file_path: Path,
    status_callback: Callable[[str], Coroutine] | None = None,
    mode: str = "normal",
    custom_prompt: str | None = None,
    thinking_mode: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    cached = await get_cached(file_path, _cache_version())
    if cached is not None:
        logger.info("Cache hit para {}", file_path.name)
        if isinstance(cached, dict):
            return cached
        return build_canonical_document(
            str(cached),
            title=file_path.stem,
            language="pt-BR",
            verbosity=verbosity_for_mode(mode),
            source_name=file_path.name,
            source_path=str(file_path),
            audience=["reader"],
        )

    task_id = state_manager.criar_tarefa(file_path, task_id=task_id)
    inicio = time.time()
    await registrar_conversao(
        task_id=task_id,
        arquivo=file_path.name,
        extensao=file_path.suffix,
        tamanho_bytes=file_path.stat().st_size,
        modo=mode,
    )

    try:
        state_manager.atualizar(
            task_id,
            etapa="Preparando arquivo",
            progresso=0.1,
        )
        state_manager.verificar_cancelamento(task_id)

        if status_callback:
            await status_callback("📄 Analisando arquivo...")

        state_manager.atualizar(
            task_id,
            etapa="Processando com IA",
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

        state_manager.verificar_cancelamento(task_id)
        if not raw_text.strip():
            raise RuntimeError("Resposta vazia do agente")

        canonical_document = build_canonical_document(
            resultado,
            title=file_path.stem,
            language="pt-BR",
            verbosity=verbosity_for_mode(mode),
            source_name=file_path.name,
            source_path=str(file_path),
            audience=["reader"],
            metadata=canonical_metadata,
            technical_warnings=technical_warnings,
        )

        state_manager.finalizar(
            task_id,
            json.dumps(canonical_document, ensure_ascii=False),
        )
        await set_cache(file_path, canonical_document, _cache_version())
        _salvar_json_canonico(canonical_document, file_path.name)

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

    except TaskCancelledError:
        logger.info("Tarefa {} cancelada pelo usuario", task_id)
        await finalizar_conversao(
            task_id=task_id,
            status="cancelled",
            erro="Cancelado pelo usuario",
            tempo_segundos=time.time() - inicio,
        )
        raise

    except Exception as e:
        logger.error("Erro no pipeline: {}: {}", type(e).__name__, e)
        record_pipeline_error("pipeline", mode=mode)
        state_manager.errar(task_id, str(e))
        fallback = _fallback_texto_simples(file_path)
        state_manager.atualizar(task_id, resultado=fallback)

        await finalizar_conversao(
            task_id=task_id,
            status="error",
            erro=str(e),
            resultado_resumo=fallback[:200],
            tempo_segundos=time.time() - inicio,
        )

        if status_callback:
            await status_callback("❌ Nao foi possivel processar o arquivo.")
        return build_canonical_document(
            fallback,
            title=file_path.stem,
            language="pt-BR",
            verbosity=verbosity_for_mode(mode),
            source_name=file_path.name,
            source_path=str(file_path),
            audience=["reader"],
        )


def _fallback_texto_simples(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        try:
            import fitz

            doc = fitz.open(file_path)
            texts = []
            for i in range(min(len(doc), 10)):
                text = doc[i].get_text().strip()
                if text:
                    texts.append(f"--- Pagina {i + 1} ---\n{text}")
            doc.close()
            if texts:
                return "\n\n".join(texts)
        except Exception:
            pass
    return (
        "Nao foi possivel processar o arquivo automaticamente. "
        "Tente enviar em formato diferente."
    )
