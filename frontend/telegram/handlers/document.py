import asyncio
import tempfile
import time
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, Document, PhotoSize
from aiogram.exceptions import TelegramRetryAfter

from frontend.telegram.adapters.file_service import download_file
from frontend.clients.api_client import ApiError
from frontend.clients import default_client

from backend.tools.logger import logger
from backend.i18n import t
from backend.log_messages import (
    LOG_TELEGRAM_API_JOB_REJECTED,
    LOG_TELEGRAM_API_CONTACT_FAILED,
    LOG_TELEGRAM_FILE_PROCESSING_ERROR,
    LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED,
    LOG_TELEGRAM_RATE_LIMIT_WAIT,
    LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES,
)
from backend.tools.validators import validate_file
from frontend.telegram.adapters.status_tracker import StatusTracker
from backend.config.settings import settings
from frontend.telegram.messages import (
    MSG_ACCESSIBLE_PACKAGE_READY,
    MSG_CONTACT_SERVER_FAILED,
    MSG_DOWNLOADING_FILE,
    MSG_DOWNLOAD_LINK_EMAILED,
    MSG_FILE_RECEIVED,
    MSG_PHOTO_RECEIVED,
    MSG_PROCESS_FAILED_BASE,
    MSG_PROCESSING_ERROR_GENERIC,
    MSG_PROCESSING_TIMEOUT,
    MSG_QUEUE_POSITION,
    MSG_SUBMIT_FAILED,
    MSG_TASK_CANCELLED,
    MSG_TASK_ENQUEUED,
    MSG_WAITING_IN_QUEUE,
)

router = Router()

client = default_client

user_modes: dict[tuple[int, int | None], str] = {}
user_emails: dict[tuple[int, int | None], str] = {}
user_task_ids: dict[tuple[int, int | None], str] = {}

POLL_INTERVAL_SECONDS = 3.0


async def _send_with_retry(
    bot,
    chat_id: int,
    msg: str,
    message_thread_id: int | None = None,
    max_retries: int = 3,
) -> None:
    """Send a Telegram message, retrying on rate-limit backoffs until successful or retries are exhausted.

    Args:
        bot (Bot): Aiogram Bot instance used for sending; no default (required).
        chat_id (int): Numeric id of the target chat; no default (required).
        msg (str): Full message text already localized by the caller via backend.i18n.t(); no default (required).
        message_thread_id (int|None): Forum-topic thread identifier or None for top-level chats (default: None).
        max_retries (int): Number of send attempts before giving up (default: 3).
    """
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id, msg, message_thread_id=message_thread_id)
            return
        except TelegramRetryAfter as e:
            wait = e.retry_after + attempt * 5
            logger.warning(
                t(LOG_TELEGRAM_RATE_LIMIT_WAIT).format(
                    wait=wait, preview=msg[:50]
                )
            )
            await asyncio.sleep(wait)
    logger.error(
        t(LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES).format(attempts=max_retries)
    )


@router.message(F.document)
async def handle_document(message: Message) -> None:
    """Incoming document file handler; acknowledges receipt in the active locale then starts processing.

    Args:
        message (Message): Aiogram Message containing the user-sent Document attachment; no default (required).
    """
    document: Document | None = message.document
    if document is None:
        return

    filename = document.file_name or "document"
    file_size = document.file_size or 0

    valid, error_msg = validate_file(filename, file_size)
    if not valid:
        await message.answer(error_msg)
        return

    mode = user_modes.pop((message.chat.id, message.message_thread_id), "normal")
    await message.answer(t(MSG_FILE_RECEIVED))
    await process_file(message, document.file_id, filename, mode=mode)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Incoming photo handler; acknowledges receipt in the active locale then starts processing as image.png.

    Args:
        message (Message): Aiogram Message containing one or more PhotoSize entries; no default (required).
    """
    photo: PhotoSize | None = message.photo[-1] if message.photo else None
    if photo is None:
        return

    mode = user_modes.pop((message.chat.id, message.message_thread_id), "normal")
    await message.answer(t(MSG_PHOTO_RECEIVED))
    await process_file(message, photo.file_id, "image.png", mode=mode)


async def process_file(
    message: Message,
    file_id: str,
    filename: str,
    mode: str = "normal",
) -> None:
    """Download a remote file locally, submit it to the processing API and wait for completion.

    Args:
        message (Message): Aiogram Message triggering the job; used only for threading/chat id context; no default (required).
        file_id (str): Telegram unique file identifier of the received attachment; no default (required).
        filename (str): Original filename to store and report inside the job; no default (required).
        mode (str): Description-detail preset requested by the user's last /detalhado|/medio|/baixo command (default: "normal").
    """
    message_thread_id = message.message_thread_id
    tracker = StatusTracker(
        message.bot, message.chat.id, filename, message_thread_id=message_thread_id
    )
    email = user_emails.get((message.chat.id, message.message_thread_id))

    try:
        with tempfile.TemporaryDirectory(dir=settings.temp_dir) as tmpdir:
            input_path = Path(tmpdir) / filename
            await tracker(t(MSG_DOWNLOADING_FILE))
            await download_file(message.bot, file_id, input_path)

            try:
                result = await client.submit_job(
                    input_path,
                    filename,
                    mode=mode,
                    email=email,
                    source="telegram",
                )
            except ApiError as e:
                logger.warning(
                    t(LOG_TELEGRAM_API_JOB_REJECTED).format(
                        status_code=e.status_code, detail=e.detail
                    )
                )
                await tracker.finish(success=False)
                await message.answer(
                    t(MSG_SUBMIT_FAILED).format(status_code=e.status_code, detail=e.detail)
                )
                return
            except Exception as e:
                logger.exception(t(LOG_TELEGRAM_API_CONTACT_FAILED))
                await tracker.finish(success=False)
                await message.answer(t(MSG_CONTACT_SERVER_FAILED))
                return

        user_emails.pop((message.chat.id, message.message_thread_id), None)
        task_id = result["task_id"]
        position = result.get("position", 1)
        user_task_ids[(message.chat.id, message.message_thread_id)] = task_id

        await tracker(t(MSG_TASK_ENQUEUED).format(task_id=task_id))
        if position > 1:
            await message.answer(
                t(MSG_QUEUE_POSITION).format(position=position)
            )

        await _poll_job(message, tracker, task_id, email)
    except Exception as e:
        logger.exception(t(LOG_TELEGRAM_FILE_PROCESSING_ERROR))
        await tracker.finish(success=False)
        await message.answer(t(MSG_PROCESSING_ERROR_GENERIC))


async def _poll_job(
    message: Message,
    tracker: StatusTracker,
    task_id: str,
    email: str | None,
) -> None:
    """Poll the API for a task's status until it completes, fails or the request timeout elapses.

    Args:
        message (Message): Aiogram Message used to deliver thread-scoped replies; no default (required).
        tracker (StatusTracker): Status message updater bound to the chat and file already initialized by the caller; no default (required).
        task_id (str): Task identifier returned by the API at submit time; no default (required).
        email (str|None): Deliver-to e-mail stored via /email or None when the user has not configured one yet; no default (required at callers).
    """
    message_thread_id = message.message_thread_id
    deadline = time.time() + max(settings.request_timeout, 60)
    last_etapa = ""
    last_pct = -1

    while time.time() < deadline:
        try:
            status = await client.get_job_status(task_id)
        except Exception as e:
            logger.warning(
                t(LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED).format(task_id=task_id, error=e)
            )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        st = status.get("status", "queued")
        etapa = status.get("etapa_atual") or ""
        pct = int((status.get("progresso") or 0.0) * 100)

        if etapa != last_etapa or pct != last_pct:
            if st == "queued":
                await tracker(t(MSG_WAITING_IN_QUEUE).format(step=etapa))
            elif etapa:
                await tracker(etapa)
            last_etapa = etapa
            last_pct = pct

        if st == "done":
            await tracker.finish(success=True)
            url = status.get("download_url")
            if url:
                if email:
                    await message.answer(
                        t(MSG_DOWNLOAD_LINK_EMAILED).format(email=email)
                    )
                else:
                    await _send_with_retry(
                        message.bot,
                        message.chat.id,
                        t(MSG_ACCESSIBLE_PACKAGE_READY).format(url=url),
                        message_thread_id=message_thread_id,
                    )
            return

        if st == "error":
            await tracker.finish(success=False)
            erros = status.get("erros") or []
            msg = t(MSG_PROCESS_FAILED_BASE)
            if erros:
                msg += f"\n{erros[0]}"
            await _send_with_retry(
                message.bot,
                message.chat.id,
                msg,
                message_thread_id=message_thread_id,
            )
            return

        if st == "cancelled":
            await tracker.finish(success=False)
            await _send_with_retry(
                message.bot,
                message.chat.id,
                t(MSG_TASK_CANCELLED),
                message_thread_id=message_thread_id,
            )
            return

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    await tracker.finish(success=False)
    await _send_with_retry(
        message.bot,
        message.chat.id,
        t(MSG_PROCESSING_TIMEOUT),
        message_thread_id=message_thread_id,
    )
