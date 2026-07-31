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
from backend.tools.validators import validate_file
from frontend.telegram.adapters.status_tracker import StatusTracker
from backend.config.settings import settings

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
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id, msg, message_thread_id=message_thread_id)
            return
        except TelegramRetryAfter as e:
            wait = e.retry_after + attempt * 5
            logger.warning(
                "Telegram rate limit, aguardando {}s: {}",
                wait,
                msg[:50],
            )
            await asyncio.sleep(wait)
    logger.error("Falha apos {} tentativas para enviar mensagem", max_retries)


@router.message(F.document)
async def handle_document(message: Message) -> None:
    document: Document | None = message.document
    if document is None:
        return

    filename = document.file_name or "documento"
    file_size = document.file_size or 0

    valid, error_msg = validate_file(filename, file_size)
    if not valid:
        await message.answer(error_msg)
        return

    mode = user_modes.pop((message.chat.id, message.message_thread_id), "normal")
    await message.answer("📄 Arquivo recebido!")
    await process_file(message, document.file_id, filename, mode=mode)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    photo: PhotoSize | None = message.photo[-1] if message.photo else None
    if photo is None:
        return

    mode = user_modes.pop((message.chat.id, message.message_thread_id), "normal")
    await message.answer("📷 Foto recebida!")
    await process_file(message, photo.file_id, "imagem.png", mode=mode)


async def process_file(
    message: Message,
    file_id: str,
    filename: str,
    mode: str = "normal",
) -> None:
    message_thread_id = message.message_thread_id
    tracker = StatusTracker(
        message.bot, message.chat.id, filename, message_thread_id=message_thread_id
    )
    email = user_emails.get((message.chat.id, message.message_thread_id))

    try:
        with tempfile.TemporaryDirectory(dir=settings.temp_dir) as tmpdir:
            input_path = Path(tmpdir) / filename
            await tracker("Baixando arquivo...")
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
                    "API recusou job do Telegram: {} - {}", e.status_code, e.detail
                )
                await tracker.finish(success=False)
                await message.answer(
                    f"❌ Erro ao enviar o arquivo para processamento ({e.status_code}): {e.detail}"
                )
                return
            except Exception as e:
                logger.exception("Falha ao contactar API pelo Telegram")
                await tracker.finish(success=False)
                await message.answer(
                    "❌ Não foi possível contatar o servidor de processamento. Tente novamente."
                )
                return

        user_emails.pop((message.chat.id, message.message_thread_id), None)
        task_id = result["task_id"]
        position = result.get("position", 1)
        user_task_ids[(message.chat.id, message.message_thread_id)] = task_id

        await tracker(f"Tarefa {task_id} enfileirada...")
        if position > 1:
            await message.answer(f"⏳ Você está na fila única (Posição: {position}).")

        await _poll_job(message, tracker, task_id, email)
    except Exception as e:
        logger.exception("Erro ao processar arquivo via Telegram")
        await tracker.finish(success=False)
        await message.answer("❌ Erro ao processar o arquivo. Tente novamente.")


async def _poll_job(
    message: Message,
    tracker: StatusTracker,
    task_id: str,
    email: str | None,
) -> None:
    message_thread_id = message.message_thread_id
    deadline = time.time() + max(settings.request_timeout, 60)
    last_etapa = ""
    last_pct = -1

    while time.time() < deadline:
        try:
            status = await client.get_job_status(task_id)
        except Exception as e:
            logger.warning("Erro ao consultar status do job {}: {}", task_id, e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        st = status.get("status", "queued")
        etapa = status.get("etapa_atual") or ""
        pct = int((status.get("progresso") or 0.0) * 100)

        if etapa != last_etapa or pct != last_pct:
            if st == "queued":
                await tracker(f"Aguardando na fila... {etapa}")
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
                        f"✅ Link de download enviado para {email}!"
                    )
                else:
                    await _send_with_retry(
                        message.bot,
                        message.chat.id,
                        f"✅ Pacote acessível gerado!\n\n📥 Link para download (válido por 7 dias):\n{url}",
                        message_thread_id=message_thread_id,
                    )
            return

        if st == "error":
            await tracker.finish(success=False)
            erros = status.get("erros") or []
            msg = "❌ Erro no processamento."
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
                "🚫 Tarefa cancelada.",
                message_thread_id=message_thread_id,
            )
            return

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    await tracker.finish(success=False)
    await _send_with_retry(
        message.bot,
        message.chat.id,
        "⏰ O processamento demorou mais que o esperado. Use /status para acompanhar.",
        message_thread_id=message_thread_id,
    )
