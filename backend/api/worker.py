from __future__ import annotations

import asyncio
import concurrent.futures
import functools
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
from backend.observability import (
    record_export,
    record_job_finished,
    record_job_started,
    record_job_status,
    record_pipeline_error,
)
from backend.services.download_token_service import criar_token
from backend.services.email_service import send_confirmation_email, send_result_email
from backend.tools.logger import logger

queued_jobs: dict[str, dict[str, Any]] = {}


def register_queued_job(
    task_id: str,
    arquivo: str,
    position: int,
    source: str,
    mode: str = "normal",
) -> None:
    queued_jobs[task_id] = {
        "task_id": task_id,
        "arquivo": arquivo,
        "source": source,
        "modo": mode,
        "status": "queued",
        "progresso": 0.0,
        "etapa_atual": f"Aguardando na fila (Posicao: {position})",
        "erros": [],
        "download_url": None,
        "inicio": time.time(),
        "fim": None,
    }
    record_job_status("queued", source=source, mode=mode)


def get_job_status(task_id: str) -> dict[str, Any] | None:
    task = state_manager.obter(task_id)
    if task is not None:
        return dict(task)
    queued = queued_jobs.get(task_id)
    return dict(queued) if queued else None


def cancel_job_status(task_id: str) -> bool:
    task = state_manager.obter(task_id)
    if task is not None:
        state_manager.cancelar(task_id)
        return True
    queued = queued_jobs.get(task_id)
    if queued is not None:
        queued["status"] = "cancelled"
        queued["etapa_atual"] = "Cancelado na fila"
        queued["fim"] = time.time()
        record_job_status(
            "cancelled",
            source=queued.get("source", "api"),
            mode=queued.get("modo", "normal"),
        )
        return True
    return False


def _mark_queued_job_running(task_id: str) -> None:
    queued = queued_jobs.get(task_id)
    if queued is None or queued.get("status") == "cancelled":
        return
    queued["status"] = "processing"
    queued["progresso"] = max(float(queued.get("progresso", 0.0)), 0.05)
    queued["etapa_atual"] = "Processamento iniciado"


def _mark_queued_job_finished(
    task_id: str,
    status: str,
    *,
    error: str = "",
    download_url: str | None = None,
) -> None:
    queued = queued_jobs.get(task_id)
    if queued is None:
        return
    queued["status"] = status
    queued["fim"] = time.time()
    if status == "done":
        queued["progresso"] = 1.0
        queued["etapa_atual"] = "Processamento concluido"
        queued["download_url"] = download_url
    elif status == "cancelled":
        queued["etapa_atual"] = "Cancelado pelo usuario"
    else:
        queued["etapa_atual"] = "Falha no processamento"
        if error:
            queued["erros"].append(error)


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
        if kwargs:
            fn = functools.partial(fn, *args, **kwargs)
            return loop.run_in_executor(self._executor, fn)
        return loop.run_in_executor(self._executor, fn, *args)

    async def run(self, job: ApiJob) -> None:
        task_id = job.task_id
        started_at = time.perf_counter()
        final_status = "error"
        current_stage = "startup"
        final_error = ""
        download_url: str | None = None

        async def status_callback(msg: str) -> None:
            state_manager.atualizar(task_id, etapa=msg)

        record_job_started(source=job.source, mode=job.mode)
        _mark_queued_job_running(task_id)

        try:
            if job.email:
                current_stage = "confirmation_email"
                await send_confirmation_email(job.email, job.filename)

            from backend.service import process

            current_stage = "pipeline"
            state_manager.atualizar(task_id, etapa="Enfileirado, aguardando...")
            canonical = await process(
                job.file_path,
                status_callback=status_callback,
                mode=job.mode,
                custom_prompt=job.custom_prompt,
                thinking_mode=job.thinking_mode,
                task_id=task_id,
            )
            state_manager.verificar_cancelamento(task_id)

            base = Path(job.filename).stem
            out_dir = job.output_dir or (settings.temp_dir / "output" / task_id)
            out_dir.mkdir(parents=True, exist_ok=True)

            current_stage = "export_txt"
            state_manager.atualizar(task_id, etapa="Exportando TXT...", progresso=0.85)
            txt_path = out_dir / f"{base}.txt"
            await self._run_in_executor(export_txt, canonical, txt_path, job.filename)
            _record_existing_output(txt_path, "txt", job)

            current_stage = "export_docx"
            state_manager.atualizar(task_id, etapa="Exportando DOCX...", progresso=0.88)
            docx_path = out_dir / f"{base}.docx"
            await self._run_in_executor(export_docx, canonical, docx_path, job.filename)
            _record_existing_output(docx_path, "docx", job)

            current_stage = "export_pdf"
            state_manager.atualizar(task_id, etapa="Exportando PDF...", progresso=0.91)
            pdf_path = out_dir / f"{base}.pdf"
            await self._run_in_executor(export_pdf, canonical, pdf_path, job.filename)
            _record_existing_output(pdf_path, "pdf", job)

            current_stage = "export_pdf_ua"
            state_manager.atualizar(task_id, etapa="Exportando PDF/UA...", progresso=0.92)
            pdf_ua_path = out_dir / f"{base}.pdf_ua.pdf"
            try:
                await self._run_in_executor(
                    export_pdf_ua,
                    canonical,
                    pdf_ua_path,
                    job.filename,
                )
                _record_existing_output(pdf_ua_path, "pdf_ua", job)
            except Exception as exc:
                logger.warning("Falha ao gerar PDF/UA: {}", exc)
                record_pipeline_error(
                    "export_pdf_ua",
                    source=job.source,
                    mode=job.mode,
                )
                pdf_ua_path = None

            current_stage = "export_html"
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
            _record_existing_output(html_path, "html", job)

            current_stage = "export_mp3"
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
                    _record_existing_output(mp3_path, "mp3", job)
                except Exception as e:
                    logger.error("Falha ao gerar MP3: {}", e)
                    record_pipeline_error(
                        "export_mp3",
                        source=job.source,
                        mode=job.mode,
                    )

            current_stage = "export_zip"
            zip_path = out_dir / f"{base}_acessivel.zip"
            package_paths = [txt_path, docx_path, pdf_path, html_path, mp3_path]
            if isinstance(pdf_ua_path, Path):
                package_paths.append(pdf_ua_path)

            await self._run_in_executor(
                _build_zip_package,
                zip_path,
                package_paths,
            )
            _record_existing_output(zip_path, "zip", job)

            current_stage = "download_token"
            token = await criar_token(out_dir, base)
            download_url = f"{settings.api_base_url.rstrip('/')}/api/v1/download/{token}"
            state_manager.registrar_download_url(task_id, download_url)
            state_manager.atualizar(
                task_id, etapa="Processamento concluido", progresso=1.0
            )

            if job.email:
                current_stage = "result_email"
                await send_result_email(
                    job.email, job.filename, download_url=download_url
                )

            final_status = "done"
            logger.info("Job {} concluido (source={})", task_id, job.source)

        except TaskCancelledError:
            final_status = "cancelled"
            logger.info("Job {} cancelado", task_id)
        except Exception as e:
            logger.exception("Erro no JobExecutor para {}", task_id)
            final_error = str(e)
            record_pipeline_error(
                current_stage,
                source=job.source,
                mode=job.mode,
            )
            state_manager.atualizar(
                task_id, status="error", erro=str(e), etapa="Falha no processamento"
            )
        finally:
            record_job_finished(
                final_status,
                source=job.source,
                mode=job.mode,
                duration_seconds=time.perf_counter() - started_at,
            )
            _mark_queued_job_finished(
                task_id,
                final_status,
                error=final_error,
                download_url=download_url,
            )
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


def _record_existing_output(path: Path | None, format_name: str, job: ApiJob) -> None:
    if path is None or not path.exists():
        return
    record_export(
        format_name,
        path.stat().st_size,
        source=job.source,
        mode=job.mode,
    )
