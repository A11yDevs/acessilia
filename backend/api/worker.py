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

from backend.agents.state_manager import TaskCancelledError, state_manager, trim_stage
from backend.config.settings import settings
from backend.services.job_store import load_record, save_status, pending_records
from backend.services.blocking import run_blocking
from backend.i18n import t
from backend.log_messages import (
    EMAIL_AUDIT_UNAVAILABLE,
    LOG_DOCX_GENERATION_FAILED,
    LOG_DOCX_SKIPPED_DISABLED,
    LOG_FAILURE_EMAIL_FAILED,
    LOG_FAILURE_EMAIL_NOT_SENT,
    LOG_JOB_CANCELLED,
    LOG_JOB_COMPLETED,
    LOG_JOB_EXECUTOR_ERROR,
    LOG_MP3_GENERATION_FAILED,
    LOG_PDF_UA_AUDIT_FAILED,
    LOG_PDF_UA_GENERATION_FAILED,
    LOG_PDF_UA_SKIPPED_DISABLED,
)
from backend.stage_messages import (
    STAGE_RESTART_CANCELLED,
    STAGE_RESTART_INTERRUPTED,
    STAGE_RESTART_INTERRUPTED_DURING,
    STAGE_RESTART_RESUBMIT,
    STAGE_PENDING_UPLOAD_MISSING,
    STAGE_CANCELLED_IN_QUEUE,
    STAGE_AUDITING_PDF_UA,
    STAGE_CANCELLED_BY_USER,
    STAGE_EXPORTING_DOCX,
    STAGE_EXPORTING_DRBENCH_MD,
    STAGE_EXPORTING_HTML,
    STAGE_EXPORTING_PDF_UA,
    STAGE_EXPORTING_TXT,
    STAGE_GENERATING_AUDIO,
    STAGE_PROCESSING_COMPLETED,
    STAGE_PROCESSING_FAILURE,
    STAGE_QUEUE_WAITING_POSITION,
)
from backend.export.exporters.audio_exporter import export_mp3
from backend.export.exporters.docx_exporter import export_docx
from backend.export.exporters.pdf_exporter import export_pdf_ua
from backend.export.exporters.txt_exporter import export_txt
from backend.export.exporters.drbench_md_exporter import export_drbench_md
from backend.export.markers import with_object_markers
from backend.export.pandoc_exporter import export_accessible_document
from backend.services.download_token_service import criar_token
from backend.tools.pdf_ua_audit import audit_pdf_ua, summarize_audit
from backend.services.email_service import (
    send_confirmation_email,
    send_failure_email,
    send_result_email,
)
from backend.services.history_service import finalizar_conversao, registrar_conversao
from backend.tools.logger import logger
from backend.tools.filenames import output_stem

queued_jobs: dict[str, dict[str, Any]] = {}


def _file_size_or_zero(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def build_download_url(token: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}/download/{token}"


async def _notify_failure(
    task_id: str, *, email: str | None, filename: str, error: str
) -> bool:
    """Tell the user a job failed without ever changing the job's outcome.

    The failure e-mail is the only feedback a user gets after the confirmation
    e-mail, so it is attempted even when the mailer raises. Neither a failed
    delivery nor a broken message may mask the pipeline error that is already
    recorded: the caller only records ``email_delivery`` and moves on.

    Args:
        task_id: Job identifier used in the warning log.
        email: Recipient address; ``None`` means the job has no e-mail to notify.
        filename: Source file name shown in the message.
        error: Job error already shown to the user, naming the failed stage.

    Returns:
        bool: ``True`` when the mailer reports delivery, ``False`` otherwise
        (no recipient, a raised exception, or an explicit delivery failure).
    """
    if not email:
        return False
    try:
        sent = await send_failure_email(email, filename, error)
    except Exception as exc:  # noqa: BLE001 - the job error must not be masked
        logger.warning(
            t(LOG_FAILURE_EMAIL_FAILED).format(task_id=task_id, error=exc)
        )
        return False
    if not sent:
        logger.warning(t(LOG_FAILURE_EMAIL_NOT_SENT).format(task_id=task_id))
    return sent


async def _persist_status(task_id: str) -> None:
    """Persist the current status, keeping a database failure from hiding the error.

    Called before the failure notification so a crash between the two cannot
    leave the job ``processing`` and make restart recovery e-mail the user a
    second time. It is also the last write in ``JobExecutor.run``'s ``finally``.
    """
    try:
        status = get_job_status(task_id)
        if status is not None:
            await run_blocking(save_status, task_id, status)
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort here
        logger.warning("Job {}: status not persisted: {}", task_id, exc)


async def _finalize_history(task_id: str, **fields: Any) -> None:
    """Finalize the history row after the notification, tolerating a DB failure.

    A locked or full history database must not suppress the failure e-mail, and
    it must not abort the rest of the recovery loop either.
    """
    try:
        await finalizar_conversao(task_id=task_id, **fields)
    except Exception as exc:  # noqa: BLE001 - notification comes first
        logger.warning("Job {}: history not finalized: {}", task_id, exc)


def register_queued_job(
    task_id: str, arquivo: str, position: int, source: str
) -> None:
    queued_jobs[task_id] = {
        "task_id": task_id,
        "arquivo": arquivo,
        "status": "queued",
        "progresso": 0.0,
        "etapa_atual": t(STAGE_QUEUE_WAITING_POSITION).format(position=position),
        "erros": [],
        "download_url": None,
        "inicio": time.time(),
        "fim": None,
    }


def get_job_status(task_id: str, *, durable: bool = True) -> dict[str, Any] | None:
    task = state_manager.obter(task_id)
    if task is not None:
        return dict(task)
    queued = queued_jobs.get(task_id)
    if not queued:
        if not durable:
            return None
        record = load_record(task_id)
        return record["status"] if record else None
    status = dict(queued)
    if status.get("status") == "queued":
        from backend.services.queue_service import unified_queue

        position = unified_queue.get_position(task_id)
        if position > 0:
            status["etapa_atual"] = t(STAGE_QUEUE_WAITING_POSITION).format(position=position)
    return status


async def get_job_status_async(task_id: str) -> dict[str, Any] | None:
    current = get_job_status(task_id, durable=False)
    if current is not None:
        return current
    record = await run_blocking(load_record, task_id)
    if record is None:
        return None
    status = record["status"]
    if status.get("email_delivery") == "pending":
        # No in-memory task owns delivery after a restart.
        status["email_delivery"] = "unknown"
    return status


def cancel_job_status(task_id: str) -> bool:
    task = state_manager.obter(task_id)
    if task is not None:
        from backend.services.queue_service import unified_queue

        active = task_id in unified_queue._active_tasks
        accepted = state_manager.cancelar(task_id, pending=active)
        if accepted and active:
            unified_queue.cancel(task_id)
        return accepted
    queued = queued_jobs.get(task_id)
    if queued is not None and queued.get("status") == "queued":
        from backend.services.queue_service import unified_queue

        if not unified_queue.cancel(task_id):
            return False
        queued["status"] = "cancelled"
        queued["etapa_atual"] = t(STAGE_CANCELLED_IN_QUEUE)
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
    #: Enclose the delivered objects in markers; None follows OBJECT_MARKERS_ENABLED.
    object_markers: bool | None = None


class JobExecutor:
    def __init__(self) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

    async def _run_in_executor(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(self._executor, functools.partial(fn, *args, **kwargs))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            try:
                await operation
            except Exception:
                pass
            raise

    async def _optional_toolbox_export(
        self,
        task_id: str,
        *,
        enabled: bool,
        stage: str,
        progress: float,
        export_fn,
        canonical: dict[str, Any],
        path: Path,
        filename: str,
        format_name: str,
        failed_log: str,
        skipped_log: str,
        completed_formats: list[str],
        optional_errors: list[str],
    ) -> Path | None:
        """Runs an export that only the Toolbox renders; returns its path, or None.

        A failure is recorded as an optional export error instead of failing
        the job, and switching the format off is a deployment choice, not an
        error.
        """
        if not enabled:
            logger.info(t(skipped_log))
            return None
        state_manager.atualizar(task_id, etapa=t(stage), progresso=progress)
        try:
            await self._run_in_executor(export_fn, canonical, path, filename)
        except Exception as exc:
            error_msg = t(failed_log).format(error=str(exc))
            logger.warning(error_msg)
            optional_errors.append(error_msg)
            state_manager.atualizar(task_id, erro=error_msg)
            _remove_partial_output(path)
            return None
        completed_formats.append(format_name)
        return path

    async def _audit_pdf_ua(
        self, task_id: str, pdf_path: Path, report_path: Path
    ) -> tuple[list[str], Path | None]:
        """veraPDF audit of the PDF/UA: the e-mail lines and the packaged report.

        Like the optional exports, a failed audit does not fail the job: the
        e-mail says it is unavailable, naming only the kind of failure, since
        the full cause carries internal Toolbox endpoints and goes to the log.
        That covers a report the e-mail cannot summarize and a report that
        cannot be written, not only a Toolbox failure. A user cancel ends the
        wait at once.
        """
        state_manager.atualizar(task_id, etapa=t(STAGE_AUDITING_PDF_UA), progresso=0.94)
        try:
            report = await _until_cancelled(task_id, audit_pdf_ua(pdf_path))
            if report is None:
                return [], None
            lines = summarize_audit(report, max_rules=settings.pdf_ua_audit_max_rules)
            await run_blocking(
                report_path.write_text,
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except TaskCancelledError:
            raise
        except Exception as exc:
            logger.warning(t(LOG_PDF_UA_AUDIT_FAILED).format(error=exc))
            _remove_partial_output(report_path)
            return [t(EMAIL_AUDIT_UNAVAILABLE).format(error=type(exc).__name__)], None
        return lines, report_path

    async def run(self, job: ApiJob) -> None:
        task_id = job.task_id
        started_at = time.time()
        out_dir: Path | None = None
        result_published = False

        async def status_callback(msg: str) -> None:
            state_manager.atualizar(task_id, etapa=msg)
            # Persisted on every stage: a process killed mid-job (out of memory,
            # a crash in a native library) loses the in-memory state, and
            # recover_pending_jobs can then still tell the user where it stopped.
            status = get_job_status(task_id)
            if status is None:
                return
            try:
                await run_blocking(save_status, task_id, status)
            except Exception as exc:  # noqa: BLE001 - progress must not fail the job
                logger.warning("Job {}: stage not persisted: {}", task_id, exc)

        try:
            queued_jobs.pop(task_id, None)
            if state_manager.obter(task_id) is None:
                state_manager.criar_tarefa(
                    job.file_path, task_id=task_id, arquivo=job.filename
                )
            await run_blocking(save_status, task_id, get_job_status(task_id))
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
                state_manager.verificar_cancelamento(task_id)

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

            # Ensures the task exists in the state_manager even if
            # service.py returned from cache without creating it.
            task = state_manager.obter(task_id)
            if task is None:
                state_manager.criar_tarefa(
                    job.file_path, task_id=task_id, arquivo=job.filename
                )

            state_manager.atualizar(task_id, status="processing")

            base = output_stem(job.filename)
            out_dir = job.output_dir or (settings.data_dir / "output" / task_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            completed_formats: list[str] = []
            optional_errors: list[str] = []

            state_manager.atualizar(task_id, etapa=t(STAGE_EXPORTING_TXT), progresso=0.85)
            txt_path = out_dir / f"{base}.txt"
            # The formats a reader gets carry the object markers when the job
            # asks for them; the benchmark markdown and the stored result do not.
            delivered = with_object_markers(canonical, job.object_markers)
            await self._run_in_executor(export_txt, delivered, txt_path, job.filename)
            completed_formats.append("txt")
            state_manager.verificar_cancelamento(task_id)

            state_manager.atualizar(task_id, etapa=t(STAGE_EXPORTING_DRBENCH_MD), progresso=0.86)
            drbench_md_path = out_dir / f"{base}.drbench.md"
            try:
                await self._run_in_executor(
                    export_drbench_md, canonical, drbench_md_path, job.filename
                )
            except Exception as exc:
                logger.warning("drbench_md export failed: {}", exc)
                _remove_partial_output(drbench_md_path)
                drbench_md_path = None
            state_manager.verificar_cancelamento(task_id)

            state_manager.atualizar(task_id, etapa=t(STAGE_EXPORTING_HTML), progresso=0.90)
            html_path = out_dir / f"{base}.html"
            await self._run_in_executor(
                export_accessible_document,
                delivered,
                html_path,
                format_name="html",
                title=base,
                profile_name="html",
            )
            completed_formats.append("html")
            state_manager.verificar_cancelamento(task_id)

            # DOCX and PDF/UA run only on the Toolbox (docs/adr/0003) and come
            # after the required formats, so a hung Toolbox cannot hold back
            # TXT/HTML. PDF/UA is the only PDF: a failure leaves the job
            # without one, with a warning in the result e-mail.
            docx_path = await self._optional_toolbox_export(
                task_id,
                enabled=settings.toolbox_docx_enabled,
                stage=STAGE_EXPORTING_DOCX,
                progress=0.92,
                export_fn=export_docx,
                canonical=delivered,
                path=out_dir / f"{base}.docx",
                filename=job.filename,
                format_name="docx",
                failed_log=LOG_DOCX_GENERATION_FAILED,
                skipped_log=LOG_DOCX_SKIPPED_DISABLED,
                completed_formats=completed_formats,
                optional_errors=optional_errors,
            )
            state_manager.verificar_cancelamento(task_id)

            pdf_ua_path = await self._optional_toolbox_export(
                task_id,
                enabled=settings.toolbox_pdf_ua_enabled,
                stage=STAGE_EXPORTING_PDF_UA,
                progress=0.93,
                export_fn=export_pdf_ua,
                canonical=delivered,
                path=out_dir / f"{base}.pdf_ua.pdf",
                filename=job.filename,
                format_name="pdf_ua",
                failed_log=LOG_PDF_UA_GENERATION_FAILED,
                skipped_log=LOG_PDF_UA_SKIPPED_DISABLED,
                completed_formats=completed_formats,
                optional_errors=optional_errors,
            )
            state_manager.verificar_cancelamento(task_id)

            async def audit() -> tuple[list[str], Path | None]:
                if not isinstance(pdf_ua_path, Path):
                    return [], None
                return await self._audit_pdf_ua(
                    task_id, pdf_ua_path, out_dir / f"{base}.pdf_ua.verapdf.json"
                )

            async def mp3() -> Path | None:
                if not txt_path.exists():
                    return None
                mp3_path = out_dir / f"{base}.mp3"
                clean_text = txt_path.read_text(encoding="utf-8")

                async def audio_progress(percent: int) -> None:
                    state_manager.atualizar(
                        task_id,
                        etapa=t(STAGE_GENERATING_AUDIO).format(percent=percent),
                        progresso=0.95,
                    )

                try:
                    await _until_cancelled(
                        task_id,
                        export_mp3(clean_text, mp3_path, progress_callback=audio_progress),
                    )
                except TaskCancelledError:
                    raise
                except Exception as e:
                    error_msg = t(LOG_MP3_GENERATION_FAILED).format(error=str(e))
                    logger.error(error_msg)
                    optional_errors.append(error_msg)
                    state_manager.atualizar(task_id, erro=error_msg)
                    _remove_partial_output(mp3_path)
                    return None
                completed_formats.append("mp3")
                return mp3_path

            # The MP3 needs only the TXT, so it runs alongside the audit: a slow
            # veraPDF does not add its whole wait to the delivery. Both end on
            # a user cancel.
            (audit_lines, audit_path), mp3_path = await asyncio.gather(audit(), mp3())
            state_manager.verificar_cancelamento(task_id)

            zip_path = out_dir / f"{base}_acessivel.zip"
            package_paths = [txt_path, html_path]
            if isinstance(docx_path, Path):
                package_paths.append(docx_path)
            if isinstance(mp3_path, Path):
                package_paths.append(mp3_path)
            if isinstance(pdf_ua_path, Path):
                package_paths.append(pdf_ua_path)
            if isinstance(audit_path, Path):
                package_paths.append(audit_path)

            await self._run_in_executor(
                _build_zip_package,
                zip_path,
                package_paths,
            )
            completed_formats.append("zip")
            state_manager.verificar_cancelamento(task_id)

            token = await criar_token(
                out_dir,
                base,
                formats=completed_formats,
                task_id=task_id,
                owner=job.email or job.source,
            )
            download_url = build_download_url(token)
            state_manager.registrar_download_url(task_id, download_url)
            state_manager.atualizar(
                task_id, etapa=t(STAGE_PROCESSING_COMPLETED), progresso=1.0,
                status="done", resultado=json.dumps(canonical, ensure_ascii=False),
                email_delivery="pending" if job.email else None,
            )
            result_published = True
            await run_blocking(save_status, task_id, get_job_status(task_id))
            await finalizar_conversao(
                task_id=task_id,
                status="done",
                pipeline=f"{settings.ai_client}-{settings.pipeline_engine}",
                resultado_resumo=str(canonical.get("title", ""))[:200],
                tempo_segundos=time.time() - started_at,
            )

            if job.email:
                try:
                    sent = await send_result_email(
                        job.email,
                        job.filename,
                        download_url=download_url,
                        completed_formats=completed_formats,
                        warnings=[*optional_errors, *_open_obligations_warning(canonical)],
                        audit=audit_lines,
                    )
                except Exception:
                    logger.warning("Result email delivery failed for job {}", task_id)
                    sent = False
                state_manager.atualizar(task_id, email_delivery="sent" if sent else "failed")
                if not sent:
                    logger.warning("Resultado do job {} nao foi enviado por e-mail", task_id)

            logger.info(
                t(LOG_JOB_COMPLETED).format(task_id=task_id, source=job.source)
            )

        except (TaskCancelledError, asyncio.CancelledError):
            if result_published:
                state_manager.atualizar(task_id, email_delivery="unknown" if job.email else None)
                return
            state_manager.atualizar(task_id, status="cancelled", etapa=t(STAGE_CANCELLED_BY_USER))
            if out_dir is not None:
                _remove_output_dir(out_dir)
            logger.info(t(LOG_JOB_CANCELLED).format(task_id=task_id))
            await finalizar_conversao(
                task_id=task_id,
                status="cancelled",
                tempo_segundos=time.time() - started_at,
            )
        except Exception as e:
            logger.exception(t(LOG_JOB_EXECUTOR_ERROR).format(task_id=task_id))
            if result_published:
                state_manager.atualizar(task_id, email_delivery="unknown" if job.email else None)
                return
            if out_dir is not None:
                _remove_output_dir(out_dir)
            task = state_manager.obter(task_id)
            if task is not None and task.get("status") == "error" and task.get("erros"):
                # process() already recorded the error with the stage it failed in.
                error = task["erros"][-1]
            else:
                error = state_manager.errar(task_id, str(e) or type(e).__name__)
            state_manager.atualizar(task_id, etapa=t(STAGE_PROCESSING_FAILURE))
            # Persist the terminal state before notifying: a crash between the
            # send and the save would leave the job "processing", and restart
            # recovery would e-mail the user a second time.
            await _persist_status(task_id)
            if job.email:
                sent = await _notify_failure(
                    task_id,
                    email=job.email,
                    filename=job.filename,
                    error=error,
                )
                state_manager.atualizar(
                    task_id, email_delivery="sent" if sent else "failed"
                )
                await _persist_status(task_id)
            # The notification must not depend on the history write: a locked
            # history database used to suppress the failure e-mail entirely.
            await _finalize_history(
                task_id,
                status="error",
                erro=error,
                tempo_segundos=time.time() - started_at,
            )
        finally:
            await _persist_status(task_id)
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


def _open_obligations_warning(canonical: dict[str, Any]) -> list[str]:
    """The PDDL obligations a delivered document still has open, for the e-mail.

    Only non-critical ones reach a delivered document (a dropped block, an
    unapplied adjudication), and nothing else tells the user about them.
    """
    metadata = canonical.get("metadata")
    summary = metadata.get("pddl_unsatisfied_summary") if isinstance(metadata, dict) else None
    return [summary] if isinstance(summary, str) and summary else []


async def _until_cancelled(task_id: str, awaitable: Any) -> Any:
    """Awaits ``awaitable``, abandoning it as soon as the user cancels the task.

    Raises:
        TaskCancelledError: When the task is cancelled before ``awaitable`` ends.
    """
    event = state_manager.evento_cancelamento(task_id)
    work = asyncio.ensure_future(awaitable)
    if event is None:
        return await work
    cancelled = asyncio.ensure_future(event.wait())
    try:
        await asyncio.wait({work, cancelled}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        cancelled.cancel()
        if not work.done():
            work.cancel()
    state_manager.verificar_cancelamento(task_id)
    return work.result()


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


async def recover_pending_jobs() -> None:
    from backend.services.queue_service import unified_queue, QueueItem
    from backend.api.routes.jobs import job_executor
    for record in await run_blocking(pending_records):
        task_id = record["task_id"]
        status = record["status"]
        if status["status"] == "cancelling":
            status.update(status="cancelled", fim=time.time(), etapa_atual=t(STAGE_RESTART_CANCELLED))
            await run_blocking(save_status, task_id, status)
            Path(record["request"]["file_path"]).unlink(missing_ok=True)
            await finalizar_conversao(task_id, status="cancelled")
            continue
        if status["status"] == "processing":
            # The last stage was persisted before the process died, so the
            # error names the page or plan step the job was on.
            stage = trim_stage(status.get("etapa_atual"))
            error = (
                t(STAGE_RESTART_INTERRUPTED_DURING).format(stage=stage)
                if stage
                else t(STAGE_RESTART_RESUBMIT)
            )
            status.update(status="error", fim=time.time(), etapa_atual=t(STAGE_RESTART_INTERRUPTED))
            status.setdefault("erros", []).append(error)
            await run_blocking(save_status, task_id, status)
            email = record["request"].get("email")
            if email:
                sent = await _notify_failure(
                    task_id,
                    email=email,
                    filename=record["request"].get("filename", ""),
                    error=error,
                )
                status["email_delivery"] = "sent" if sent else "failed"
                await run_blocking(save_status, task_id, status)
            await _finalize_history(task_id, status="error", erro=error)
            continue
        if unified_queue.get_position(task_id):
            continue
        payload = record["request"]
        payload["file_path"] = Path(payload["file_path"])
        payload["output_dir"] = Path(payload["output_dir"]) if payload.get("output_dir") else None
        job = ApiJob(**payload)
        if not job.file_path.is_file():
            error = t(STAGE_PENDING_UPLOAD_MISSING)
            status.update(status="error", fim=time.time(), erros=[error])
            await run_blocking(save_status, task_id, status)
            # A queued job never reached the executor, so its history row was
            # never created. Create it before finalizing, or the failure would
            # be visible in the job page but missing from history/statistics.
            try:
                await registrar_conversao(
                    task_id=task_id,
                    arquivo=job.filename,
                    extensao=job.file_path.suffix,
                    tamanho_bytes=_file_size_or_zero(job.file_path),
                    modo=job.mode,
                )
            except Exception as exc:  # noqa: BLE001 - history is best-effort
                logger.warning("Job {}: history not registered: {}", task_id, exc)
            if job.email:
                sent = await _notify_failure(
                    task_id,
                    email=job.email,
                    filename=job.filename,
                    error=error,
                )
                status["email_delivery"] = "sent" if sent else "failed"
                await run_blocking(save_status, task_id, status)
            await _finalize_history(task_id, status="error", erro=error)
            continue
        queued_jobs[task_id] = status
        await unified_queue.enqueue(QueueItem(file_path=job.file_path, filename=job.filename, source=job.source, task_id=task_id, callback=job_executor.run, callback_args={"job": job}))
