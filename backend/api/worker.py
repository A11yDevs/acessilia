from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import json
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.agents.state_manager import TaskCancelledError, state_manager
from backend.config.settings import settings
from backend.export.exporters.audio_exporter import export_mp3
from backend.export.exporters.docx_exporter import export_docx
from backend.export.exporters.pdf_exporter import export_pdf
from backend.export.exporters.pdf_exporter import export_pdf_ua
from backend.export.exporters.txt_exporter import export_txt
from backend.export.pandoc_exporter import export_accessible_document
from backend.services.download_token_service import criar_token
from backend.services.email_service import send_confirmation_email, send_result_email
from backend.services.history_service import finalizar_conversao, registrar_conversao
from backend.tools.logger import logger

queued_jobs: dict[str, dict[str, Any]] = {}


def _file_size_or_zero(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def build_download_url(token: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}/download/{token}"


def register_queued_job(
    task_id: str, arquivo: str, position: int, source: str
) -> None:
    queued_jobs[task_id] = {
        "task_id": task_id,
        "arquivo": arquivo,
        "status": "queued",
        "progresso": 0.0,
        "etapa_atual": f"Aguardando na fila (Posicao: {position})",
        "erros": [],
        "download_url": None,
        "inicio": time.time(),
        "fim": None,
    }


def get_job_status(task_id: str) -> dict[str, Any] | None:
    task = state_manager.obter(task_id)
    if task is not None:
        return dict(task)
    queued = queued_jobs.get(task_id)
    if not queued:
        return None
    status = dict(queued)
    if status.get("status") == "queued":
        from backend.services.queue_service import unified_queue

        position = unified_queue.get_position(task_id)
        if position > 0:
            status["etapa_atual"] = f"Aguardando na fila (Posicao: {position})"
    return status


def cancel_job_status(task_id: str) -> bool:
    task = state_manager.obter(task_id)
    if task is not None:
        return state_manager.cancelar(task_id)
    queued = queued_jobs.get(task_id)
    if queued is not None and queued.get("status") == "queued":
        from backend.services.queue_service import unified_queue

        if not unified_queue.cancel(task_id):
            return False
        queued["status"] = "cancelled"
        queued["etapa_atual"] = "Cancelado na fila"
        queued["fim"] = time.time()
        return True
    return False


@dataclass
class ApiJob:
    task_id: str
    file_path: Path
    filename: str
    mode: str = "normal"
    custom_prompt: str | None = None
    thinking_mode: bool = False
    email: str | None = None
    source: str = "api"
    output_dir: Path | None = None


class JobExecutor:
    def __init__(self) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

    def _run_in_executor(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._executor, functools.partial(fn, *args, **kwargs))

    async def run(self, job: ApiJob) -> None:
        task_id = job.task_id
        started_at = time.time()
        out_dir: Path | None = None

        async def status_callback(msg: str) -> None:
            state_manager.atualizar(task_id, etapa=msg)

        try:
            queued_jobs.pop(task_id, None)
            if state_manager.obter(task_id) is None:
                state_manager.criar_tarefa(
                    job.file_path, task_id=task_id, arquivo=job.filename
                )
            await registrar_conversao(
                task_id=task_id,
                arquivo=job.filename,
                extensao=job.file_path.suffix,
                tamanho_bytes=_file_size_or_zero(job.file_path),
                modo=job.mode,
            )
            state_manager.atualizar(task_id, etapa="Enfileirado, aguardando...")

            if job.email:
                await send_confirmation_email(job.email, job.filename)

            from backend.service import process

            canonical = await process(
                job.file_path,
                status_callback=status_callback,
                mode=job.mode,
                custom_prompt=job.custom_prompt,
                thinking_mode=job.thinking_mode,
                task_id=task_id,
            )
            state_manager.verificar_cancelamento(task_id)

            # Garante que a task existe no state_manager mesmo se
            # service.py retornou de cache sem criar a tarefa
            task = state_manager.obter(task_id)
            if task is None:
                state_manager.criar_tarefa(
                    job.file_path, task_id=task_id, arquivo=job.filename
                )

            state_manager.atualizar(task_id, status="processing")

            base = Path(job.filename).stem
            out_dir = job.output_dir or (settings.data_dir / "output" / task_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            completed_formats: list[str] = []
            optional_errors: list[str] = []

            state_manager.atualizar(task_id, etapa="Exportando TXT...", progresso=0.85)
            txt_path = out_dir / f"{base}.txt"
            await self._run_in_executor(export_txt, canonical, txt_path, job.filename)
            completed_formats.append("txt")
            state_manager.verificar_cancelamento(task_id)

            state_manager.atualizar(task_id, etapa="Exportando DOCX...", progresso=0.88)
            docx_path = out_dir / f"{base}.docx"
            await self._run_in_executor(export_docx, canonical, docx_path, job.filename)
            completed_formats.append("docx")
            state_manager.verificar_cancelamento(task_id)

            state_manager.atualizar(task_id, etapa="Exportando PDF...", progresso=0.91)
            pdf_path = out_dir / f"{base}.pdf"
            await self._run_in_executor(export_pdf, canonical, pdf_path, job.filename)
            completed_formats.append("pdf")
            state_manager.verificar_cancelamento(task_id)

            state_manager.atualizar(task_id, etapa="Exportando PDF/UA...", progresso=0.92)
            pdf_ua_path = out_dir / f"{base}.pdf_ua.pdf"
            try:
                await self._run_in_executor(
                    export_pdf_ua,
                    canonical,
                    pdf_ua_path,
                    job.filename,
                )
                completed_formats.append("pdf_ua")
            except Exception as exc:
                logger.warning("Falha ao gerar PDF/UA: {}", exc)
                error_msg = f"Falha ao gerar PDF/UA: {exc}"
                optional_errors.append(error_msg)
                state_manager.atualizar(task_id, erro=error_msg)
                _remove_partial_output(pdf_ua_path)
                pdf_ua_path = None
            state_manager.verificar_cancelamento(task_id)

            state_manager.atualizar(task_id, etapa="Exportando HTML...", progresso=0.93)
            html_path = out_dir / f"{base}.html"
            await self._run_in_executor(
                export_accessible_document,
                canonical,
                html_path,
                format_name="html",
                title=base,
                profile_name="html",
            )
            completed_formats.append("html")
            state_manager.verificar_cancelamento(task_id)

            mp3_path = out_dir / f"{base}.mp3"
            if txt_path.exists():
                clean_text = txt_path.read_text(encoding="utf-8")

                async def audio_progress(percent: int) -> None:
                    state_manager.atualizar(
                        task_id, etapa=f"Gerando audio... {percent}%", progresso=0.95
                    )

                try:
                    await export_mp3(
                        clean_text, mp3_path, progress_callback=audio_progress
                    )
                    completed_formats.append("mp3")
                except Exception as e:
                    logger.error("Falha ao gerar MP3: {}", e)
                    error_msg = f"Falha ao gerar MP3: {e}"
                    optional_errors.append(error_msg)
                    state_manager.atualizar(task_id, erro=error_msg)
                    _remove_partial_output(mp3_path)
                    mp3_path = None
            state_manager.verificar_cancelamento(task_id)

            zip_path = out_dir / f"{base}_acessivel.zip"
            package_paths = [txt_path, docx_path, pdf_path, html_path]
            if isinstance(mp3_path, Path):
                package_paths.append(mp3_path)
            if isinstance(pdf_ua_path, Path):
                package_paths.append(pdf_ua_path)

            await self._run_in_executor(
                _build_zip_package,
                zip_path,
                package_paths,
            )
            completed_formats.append("zip")
            state_manager.verificar_cancelamento(task_id)

            token = await criar_token(out_dir, base, formats=completed_formats)
            download_url = build_download_url(token)
            state_manager.registrar_download_url(task_id, download_url)
            state_manager.atualizar(
                task_id, etapa="Processamento concluido", progresso=1.0,
                status="done", resultado=json.dumps(canonical, ensure_ascii=False),
            )
            await finalizar_conversao(
                task_id=task_id,
                status="done",
                pipeline=f"{settings.ai_client}-{settings.pipeline_engine}",
                resultado_resumo=str(canonical.get("title", ""))[:200],
                tempo_segundos=time.time() - started_at,
            )

            if job.email:
                sent = await send_result_email(
                    job.email,
                    job.filename,
                    download_url=download_url,
                    completed_formats=completed_formats,
                    warnings=optional_errors,
                )
                if not sent:
                    logger.warning("Resultado do job {} nao foi enviado por e-mail", task_id)

            logger.info("Job {} concluido (source={})", task_id, job.source)

        except TaskCancelledError:
            logger.info("Job {} cancelado", task_id)
            await finalizar_conversao(
                task_id=task_id,
                status="cancelled",
                tempo_segundos=time.time() - started_at,
            )
        except Exception as e:
            logger.exception("Erro no JobExecutor para {}", task_id)
            if out_dir is not None:
                _remove_output_dir(out_dir)
            state_manager.atualizar(
                task_id, status="error", erro=str(e), etapa="Falha no processamento"
            )
            await finalizar_conversao(
                task_id=task_id,
                status="error",
                erro=str(e),
                tempo_segundos=time.time() - started_at,
            )
        finally:
            if job.file_path.exists():
                try:
                    job.file_path.unlink()
                except OSError:
                    pass


def _build_zip_package(zip_path: Path, out_paths: list[Path]) -> None:
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for out_path in out_paths:
            if out_path.exists():
                archive.write(out_path, arcname=out_path.name)


def _remove_partial_output(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Falha ao remover artefato parcial {}: {}", path, exc)


def _remove_output_dir(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError as exc:
        logger.warning("Falha ao remover output parcial {}: {}", path, exc)


def expirar_status_fila(max_age_seconds: int, now: float | None = None) -> int:
    now = now or time.time()
    expired = [
        task_id
        for task_id, job in queued_jobs.items()
        if job.get("status") in ("done", "error", "cancelled")
        and job.get("fim") is not None
        and (now - job["fim"]) > max_age_seconds
    ]
    for task_id in expired:
        queued_jobs.pop(task_id, None)
    return len(expired)
