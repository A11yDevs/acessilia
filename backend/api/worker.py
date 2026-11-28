from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import functools
import json
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Coroutine, cast

from acessilia_core.blocking import run_blocking
from acessilia_core.config import CoreConfig, ToolboxConfig
from acessilia_core.export.catalog import CATALOG, DOCX, DRBENCH_MD, HTML, PDF_UA, TXT
from acessilia_core.export.exporters.audio_exporter import export_mp3
from acessilia_core.export.exporters.docx_exporter import export_docx
from acessilia_core.export.exporters.drbench_md_exporter import export_drbench_md
from acessilia_core.export.exporters.pdf_exporter import export_pdf_ua
from acessilia_core.export.exporters.txt_exporter import export_txt
from acessilia_core.export.markers import with_object_markers
from acessilia_core.export.pandoc_exporter import export_accessible_document
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
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
from acessilia_core.i18n.stage_messages import (
    STAGE_AUDITING_PDF_UA,
    STAGE_CANCELLATION_WAITING,
    STAGE_CANCELLED_BY_USER,
    STAGE_CANCELLED_IN_QUEUE,
    STAGE_PENDING_UPLOAD_MISSING,
    STAGE_PROCESSING_COMPLETED,
    STAGE_PROCESSING_FAILURE,
    STAGE_QUEUE_WAITING_POSITION,
    STAGE_RESTART_CANCELLED,
    STAGE_RESTART_INTERRUPTED,
    STAGE_RESTART_INTERRUPTED_DURING,
    STAGE_RESTART_RESUBMIT,
)
from acessilia_core.logger import logger
from acessilia_core.ports import RunOutcome
from acessilia_core.toolbox.pdf_ua_audit import audit_pdf_ua, summarize_audit
from backend.agents.state_manager import TaskCancelledError, state_manager, trim_stage
from backend.api.export_plan import (
    AUDIO_STEP,
    PACKAGE_ORDER,
    PACKAGE_STEP,
    SERIAL_EXPORT_STEPS,
    ExportStep,
)
from backend.config.core_config import core_config_from_settings
from backend.config.effective import effective_configuration
from backend.config.settings import Settings, settings
from backend.services import job_checkpoint, shutdown
from backend.services.download_token_service import criar_token
from backend.services.email_service import (
    send_confirmation_email,
    send_failure_email,
    send_result_email,
)
from backend.services.filenames import output_stem
from backend.services.history_service import finalizar_conversao, registrar_conversao
from backend.services.job_store import (
    load_record,
    pending_records,
    reconcile_started_attempts,
    save_attempt_marker,
    save_attempt_result,
    save_attempt_start,
    save_status,
)

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


def _cancellation_progress(status: dict[str, Any]) -> dict[str, Any]:
    status = dict(status)
    requested = status.get("cancellation_requested_at")
    status.pop("cancellation_elapsed_seconds", None)
    if status.get("status") == "cancelling" and requested is not None:
        elapsed = max(0, int(time.time() - requested))
        status["cancellation_elapsed_seconds"] = elapsed
        status["etapa_atual"] = t(STAGE_CANCELLATION_WAITING).format(seconds=elapsed)
    return status


def get_job_status(task_id: str, *, durable: bool = True) -> dict[str, Any] | None:
    task = state_manager.obter(task_id)
    if task is not None:
        return _cancellation_progress(task)
    queued = queued_jobs.get(task_id)
    if not queued:
        if not durable:
            return None
        record = load_record(task_id)
        if record is None:
            return None
        return _cancellation_progress(record["status"])
    status = dict(queued)
    if status.get("status") == "queued":
        from backend.services.queue_service import unified_queue

        position = unified_queue.get_position(task_id)
        if position > 0:
            status["etapa_atual"] = t(STAGE_QUEUE_WAITING_POSITION).format(position=position)
    return _cancellation_progress(status)


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
    return _cancellation_progress(status)


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
    # "processing" here is a job recovery put back in the queue: it has no
    # in-memory task yet but is still waiting, so it must be cancellable (#407).
    if queued is not None and queued.get("status") in {"queued", "processing"}:
        from backend.services.queue_service import unified_queue

        if not unified_queue.cancel(task_id):
            return False
        queued["status"] = "cancelled"
        queued["etapa_atual"] = t(STAGE_CANCELLED_IN_QUEUE)
        queued["fim"] = time.time()
        job_checkpoint.clear(task_id)
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


def _job_from_record(record: dict[str, Any]) -> ApiJob:
    """The job a durable record describes; raises on a malformed payload."""
    payload = dict(record["request"])
    payload["file_path"] = Path(payload["file_path"])
    payload["output_dir"] = (
        Path(payload["output_dir"]) if payload.get("output_dir") else None
    )
    return ApiJob(**payload)


def _required_export_fields(step: ExportStep) -> tuple[str, str, float]:
    """The non-optional fields every remote export step must carry."""
    assert step.requires_flag is not None
    assert step.stage_msgid is not None
    assert step.progress is not None
    return step.requires_flag, step.stage_msgid, step.progress


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
        optional: bool = True,
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
        except TaskCancelledError:
            _remove_partial_output(path)
            raise
        except Exception as exc:
            if not optional:
                raise
            error_msg = t(failed_log).format(error=str(exc))
            logger.warning(error_msg)
            optional_errors.append(error_msg)
            state_manager.atualizar(task_id, erro=error_msg)
            _remove_partial_output(path)
            return None
        completed_formats.append(format_name)
        return path

    async def _audit_pdf_ua(
        self,
        task_id: str,
        pdf_path: Path,
        report_path: Path,
        toolbox: ToolboxConfig,
        max_rules: int,
    ) -> tuple[list[str], Path | None]:
        """veraPDF audit of the PDF/UA: the e-mail lines and the packaged report.

        Like the optional exports, a failed audit does not fail the job: the
        e-mail says it is unavailable, naming only the kind of failure, since
        the full cause carries internal Toolbox endpoints and goes to the log.
        That covers a report the e-mail cannot summarize and a report that
        cannot be written, not only a Toolbox failure. A user cancel ends the
        wait at once. ``toolbox`` and ``max_rules`` (``PDF_UA_AUDIT_MAX_RULES``)
        are the job's, taken at its start.
        """
        state_manager.atualizar(task_id, etapa=t(STAGE_AUDITING_PDF_UA), progresso=0.94)
        try:
            report = await _until_cancelled(task_id, audit_pdf_ua(pdf_path, toolbox=toolbox))
            if report is None:
                return [], None
            lines = summarize_audit(report, max_rules=max_rules)
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

    async def _restore_from_record(self, task_id: str) -> bool:
        """Re-apply the durable progress of a job interrupted by a restart.

        Returns ``True`` when the record says the job was already processing, so
        the caller skips the one-time steps (confirmation e-mail, queue label).
        """
        try:
            record = await run_blocking(load_record, task_id)
        except Exception as exc:  # noqa: BLE001 - a missing record is not fatal here
            logger.warning("Job {}: durable status not read: {}", task_id, exc)
            return False
        if not record or record["status"].get("status") != "processing":
            return False
        state_manager.restaurar(task_id, record["status"])
        return True

    async def _start_attempt(
        self,
        task_id: str,
        job: ApiJob,
        job_config: CoreConfig,
        run_settings: Settings,
        *,
        resumed: bool,
    ) -> str | None:
        """Append the attempt's configuration and return its id (#944).

        The configuration snapshot is immutable; the result is filled later by
        :meth:`_finish_attempt`. Both the build and the write are best effort:
        an audit failure must not fail a job whose pipeline has not started,
        and cancellation is not caught (``CancelledError`` is a
        ``BaseException``). The status carries the attempt id before the
        atomic snapshot write, so the audit can tell a stale record from the
        current attempt even when that write is the one that fails.
        """
        attempt = {
            "id": uuid.uuid4().hex,
            "captured_at": datetime.now(UTC).isoformat(),
            "resumed": resumed,
        }
        # The marker exists before the builder can fail: a known attempt
        # without a snapshot must not leave the previous one looking current.
        state_manager.definir_tentativa(
            task_id, str(attempt["id"]), str(attempt["captured_at"])
        )
        try:
            marked = await run_blocking(
                save_attempt_marker,
                task_id,
                str(attempt["id"]),
                str(attempt["captured_at"]),
            )
            if not marked:
                logger.warning("Job {}: attempt marker was not persisted", task_id)
        except Exception as exc:  # noqa: BLE001 - the marker is best-effort
            logger.warning(
                "Job {}: attempt marker not persisted: {}",
                task_id,
                type(exc).__name__,
            )
        run = {
            "mode": job.mode,
            "custom_prompt": job.custom_prompt,
            "thinking_mode": job.thinking_mode,
            "object_markers_requested": job.object_markers,
        }
        try:
            configuration = await run_blocking(
                effective_configuration,
                job_config,
                run=run,
                attempt=attempt,
                settings=run_settings,
            )
        except Exception as exc:  # noqa: BLE001 - the audit record is best-effort
            logger.warning(
                "Job {}: effective configuration not built: {}",
                task_id,
                type(exc).__name__,
            )
            return None
        try:
            await run_blocking(
                save_attempt_start, task_id, attempt, configuration
            )
        except Exception as exc:  # noqa: BLE001 - the audit record is best-effort
            logger.warning(
                "Job {}: effective configuration not persisted: {}",
                task_id,
                type(exc).__name__,
            )
            return None
        return str(attempt["id"])

    async def _finish_attempt(
        self,
        task_id: str,
        attempt_id: str | None,
        *,
        state: str,
        outcome: RunOutcome,
        error_type: str | None = None,
    ) -> None:
        """Fill the attempt's result from the run outcome (#944), best effort."""
        if attempt_id is None:
            return
        try:
            await run_blocking(
                save_attempt_result,
                task_id,
                attempt_id,
                state=state,
                origin=outcome.result_origin,
                reused_phases=outcome.reused_phases,
                error_type=error_type,
            )
        except Exception as exc:  # noqa: BLE001 - the audit result is best-effort
            logger.warning(
                "Job {}: attempt result not persisted: {}",
                task_id,
                type(exc).__name__,
            )

    async def _prepare_run(
        self, task_id: str, job: ApiJob, *, resumed: bool
    ) -> tuple[Settings, CoreConfig, int, str | None]:
        """Take one settings snapshot and append the attempt (#380, #944).

        The snapshot feeds the core's ``CoreConfig``, the cache variant, the
        audit's e-mail limit and the effective record, so they all describe
        the same start. The pipeline engine and its orchestrator remain
        process-level values fixed at import.
        """
        run_settings = copy.copy(settings)
        job_config = core_config_from_settings(run_settings)
        audit_max_rules = run_settings.pdf_ua_audit_max_rules
        attempt_id = await self._start_attempt(
            task_id, job, job_config, run_settings, resumed=resumed
        )
        return run_settings, job_config, audit_max_rules, attempt_id

    async def _begin_job(self, task_id: str, job: ApiJob) -> bool:
        """Create the task, restore a durable record and register the start.

        Returns whether the job is resumed; the confirmation e-mail is sent
        only for a fresh job (#407).
        """
        resumed = state_manager.obter(task_id) is not None
        queued_jobs.pop(task_id, None)
        if state_manager.obter(task_id) is None:
            state_manager.criar_tarefa(
                job.file_path, task_id=task_id, arquivo=job.filename
            )
            if await self._restore_from_record(task_id):
                resumed = True
        await run_blocking(save_status, task_id, get_job_status(task_id))
        await registrar_conversao(
            task_id=task_id,
            arquivo=job.filename,
            extensao=job.file_path.suffix,
            tamanho_bytes=_file_size_or_zero(job.file_path),
            modo=job.mode,
        )
        if not resumed:
            state_manager.atualizar(task_id, etapa="Enfileirado, aguardando...")
        if job.email and not resumed:
            await send_confirmation_email(job.email, job.filename)
            state_manager.verificar_cancelamento(task_id)
        return resumed

    def _status_callback(self, task_id: str) -> Callable[[str], Coroutine[Any, Any, None]]:
        """The progress callback a run uses, persisting every stage (#407)."""

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

        return status_callback

    async def run(self, job: ApiJob) -> None:
        task_id = job.task_id
        started_at = time.time()
        out_dir: Path | None = None
        result_published = False
        resumed = False
        preserve_for_resume = False
        status_callback = self._status_callback(task_id)
        outcome = RunOutcome()
        attempt_id: str | None = None

        try:
            resumed = await self._begin_job(task_id, job)

            from backend.service import process

            # One snapshot for the whole job (ADR-0016, step 3); it also
            # feeds the effective record (#380).
            run_settings, job_config, audit_max_rules, attempt_id = (
                await self._prepare_run(task_id, job, resumed=resumed)
            )
            canonical = await process(
                job.file_path,
                status_callback=status_callback,
                mode=job.mode,
                custom_prompt=job.custom_prompt,
                thinking_mode=job.thinking_mode,
                task_id=task_id,
                display_filename=job.filename,
                resumed=resumed,
                config=job_config,
                settings_snapshot=run_settings,
                outcome=outcome,
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
            out_dir = job.output_dir or (job_config.paths.data_dir / "output" / task_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            completed_formats: list[str] = []
            optional_errors: list[str] = []
            # The job's config: the skip decisions below, the exporters and
            # the audit read the values the pipeline ran with.
            export, toolbox = job_config.export, job_config.toolbox

            paths: dict[str, Path | None] = {}
            delivered = canonical
            local_exports = {
                TXT.spec.id: lambda path: self._run_in_executor(export_txt, delivered, path, job.filename),
                DRBENCH_MD.spec.id: lambda path: self._run_in_executor(export_drbench_md, canonical, path, job.filename),
                HTML.spec.id: lambda path: self._run_in_executor(
                    export_accessible_document, delivered, path,
                    format_name=HTML.spec.id, title=base, profile_name=HTML.spec.id,
                ),
            }
            remote_exports: dict[str, tuple[Callable[..., Path], str, str]] = {
                DOCX.spec.id: (export_docx, LOG_DOCX_GENERATION_FAILED, LOG_DOCX_SKIPPED_DISABLED),
                PDF_UA.spec.id: (export_pdf_ua, LOG_PDF_UA_GENERATION_FAILED, LOG_PDF_UA_SKIPPED_DISABLED),
            }
            # The five serial exports keep their existing order. Audio and
            # audit still run concurrently afterwards, followed by packaging.
            for step in SERIAL_EXPORT_STEPS:
                delivery = CATALOG[step.format_id]
                path = out_dir / delivery.output_filename(base)
                if delivery.spec.execution == "remote":
                    requires_flag, stage, progress = _required_export_fields(step)
                    exporter, failed_log, skipped_log = remote_exports[step.format_id]
                    export_kwargs: dict[str, Any] = {"export": export, "toolbox": toolbox}
                    if step.format_id == PDF_UA.spec.id:
                        export_kwargs["check_cancelled"] = functools.partial(
                            state_manager.verificar_cancelamento, task_id
                        )
                    paths[step.format_id] = await self._optional_toolbox_export(
                        task_id, enabled=getattr(export, requires_flag),
                        stage=stage, progress=progress,
                        export_fn=functools.partial(exporter, **export_kwargs),
                        canonical=delivered, path=path, filename=job.filename,
                        format_name=step.format_id, failed_log=failed_log, skipped_log=skipped_log,
                        completed_formats=completed_formats, optional_errors=optional_errors,
                        optional=step.optional,
                    )
                else:
                    state_manager.atualizar(task_id, etapa=t(cast(str, step.stage_msgid)), progresso=step.progress)
                    if step.format_id == TXT.spec.id:
                        # Internal benchmark output and stored result keep the
                        # original canonical; delivered formats carry markers.
                        delivered = with_object_markers(canonical, job.object_markers, export)
                    try:
                        await local_exports[step.format_id](path)
                    except Exception as exc:
                        if not step.optional:
                            raise
                        logger.warning("{} export failed: {}", step.format_id, exc)
                        _remove_partial_output(path)
                        paths[step.format_id] = None
                    else:
                        paths[step.format_id] = path
                        if delivery.downloadable:
                            completed_formats.append(step.format_id)
                state_manager.verificar_cancelamento(task_id)

            txt_path, pdf_ua_path = cast(Path, paths[TXT.spec.id]), paths[PDF_UA.spec.id]
            audio_step, package_step = AUDIO_STEP, PACKAGE_STEP
            async def audit() -> tuple[list[str], Path | None]:
                if not isinstance(pdf_ua_path, Path):
                    return [], None
                return await self._audit_pdf_ua(
                    task_id, pdf_ua_path, out_dir / f"{base}.pdf_ua.verapdf.json", toolbox,
                    audit_max_rules,
                )

            async def mp3() -> Path | None:
                if not txt_path.exists():
                    return None
                mp3_path = out_dir / CATALOG[audio_step.format_id].output_filename(base)
                clean_text = txt_path.read_text(encoding="utf-8")

                async def audio_progress(percent: int) -> None:
                    state_manager.atualizar(
                        task_id,
                        etapa=t(cast(str, audio_step.stage_msgid)).format(percent=percent),
                        progresso=audio_step.progress,
                    )

                try:
                    await _until_cancelled(
                        task_id,
                        export_mp3(
                            clean_text, mp3_path, export.tts_voice, progress_callback=audio_progress
                        ),
                    )
                except TaskCancelledError:
                    raise
                except Exception as e:
                    if not audio_step.optional:
                        raise
                    error_msg = t(LOG_MP3_GENERATION_FAILED).format(error=str(e))
                    logger.error(error_msg)
                    optional_errors.append(error_msg)
                    state_manager.atualizar(task_id, erro=error_msg)
                    _remove_partial_output(mp3_path)
                    return None
                completed_formats.append(audio_step.format_id)
                return mp3_path

            # The MP3 needs only the TXT, so it runs alongside the audit: a slow
            # veraPDF does not add its whole wait to the delivery. Both end on
            # a user cancel.
            (audit_lines, audit_path), mp3_path = await asyncio.gather(audit(), mp3())
            state_manager.verificar_cancelamento(task_id)

            paths[audio_step.format_id] = mp3_path
            zip_path = out_dir / CATALOG[package_step.format_id].output_filename(base)
            package_paths = [
                paths[format_id] for format_id in PACKAGE_ORDER
                if CATALOG[format_id].packaged_in_zip and isinstance(paths.get(format_id), Path)
            ]
            if isinstance(audit_path, Path):
                package_paths.append(audit_path)

            await self._run_in_executor(
                _build_zip_package,
                zip_path,
                package_paths,
            )
            completed_formats.append(package_step.format_id)
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
            await self._finish_attempt(
                task_id, attempt_id, state="completed", outcome=outcome
            )
            await run_blocking(save_status, task_id, get_job_status(task_id))
            await finalizar_conversao(
                task_id=task_id,
                status="done",
                pipeline=f"{run_settings.ai_client}-{run_settings.pipeline_engine}",
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
            if shutdown.shutting_down():
                # The queue worker stops the callback on a normal restart. Keep
                # the durable record, upload and checkpoints so the next startup
                # resumes the job instead of losing it (#407).
                await self._finish_attempt(
                    task_id, attempt_id, state="interrupted", outcome=outcome
                )
                preserve_for_resume = True
                logger.info(
                    "Job {}: service shutdown; keeping it resumable", task_id
                )
                raise
            if result_published:
                state_manager.atualizar(task_id, email_delivery="unknown" if job.email else None)
                return
            state_manager.atualizar(task_id, status="cancelled", etapa=t(STAGE_CANCELLED_BY_USER))
            await self._finish_attempt(
                task_id, attempt_id, state="cancelled", outcome=outcome
            )
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
            await self._finish_attempt(
                task_id,
                attempt_id,
                state="failed",
                outcome=outcome,
                error_type=type(e).__name__,
            )
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
            if not preserve_for_resume:
                await _persist_status(task_id)
                try:
                    await run_blocking(job_checkpoint.clear, task_id)
                except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                    logger.warning("Job {}: checkpoints not cleared: {}", task_id, exc)
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


async def _recover_cancelling(task_id: str, record: dict[str, Any], status: dict[str, Any]) -> None:
    """Finish a cancel interrupted by a restart, closing abandoned attempts."""
    await run_blocking(reconcile_started_attempts, task_id)
    status.update(status="cancelled", fim=time.time(), etapa_atual=t(STAGE_RESTART_CANCELLED))
    await run_blocking(save_status, task_id, status)
    Path(record["request"]["file_path"]).unlink(missing_ok=True)
    await run_blocking(job_checkpoint.clear, task_id)
    await finalizar_conversao(task_id, status="cancelled")


async def recover_pending_jobs() -> None:
    from backend.api.routes.jobs import job_executor
    from backend.services.queue_service import QueueItem, unified_queue
    for record in await run_blocking(pending_records):
        task_id = record["task_id"]
        status = record["status"]
        if status["status"] == "cancelling":
            await _recover_cancelling(task_id, record, status)
            continue
        if status["status"] == "processing":
            # A job that wrote a pipeline checkpoint continues where it stopped;
            # one without a usable checkpoint fails as it did before #407.
            job: ApiJob | None = None
            try:
                job = _job_from_record(record)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Job {}: resume record is unusable: {}", task_id, exc)
            tracked = unified_queue.get_position(task_id) or (
                task_id in unified_queue._active_tasks
            )
            if tracked:
                # A previous recovery already put this job back in the queue:
                # leave its processing status and checkpoints untouched.
                continue
            await run_blocking(reconcile_started_attempts, task_id)
            if (
                settings.job_resume_on_restart
                and job is not None
                and job.file_path.is_file()
                and job_checkpoint.resumable(task_id)
            ):
                queued_jobs[task_id] = status
                await unified_queue.enqueue(
                    QueueItem(
                        file_path=job.file_path,
                        filename=job.filename,
                        source=job.source,
                        task_id=task_id,
                        callback=job_executor.run,
                        callback_args={"job": job},
                    )
                )
                logger.info("Job {}: resuming from its checkpoint", task_id)
                continue
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
            await run_blocking(job_checkpoint.clear, task_id)
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
        job = _job_from_record(record)
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
