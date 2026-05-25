import asyncio
import tempfile
import zipfile
from pathlib import Path

from aiogram import Router, F
from aiogram.types import FSInputFile, Message, Document, PhotoSize
from aiogram.exceptions import TelegramRetryAfter

from bot.services.file_service import download_file
from bot.agente_mestre import process
from bot.agents.state_manager import TaskCancelledError
from bot.exporters.txt_exporter import export_txt
from bot.exporters.docx_exporter import export_docx
from bot.exporters.pdf_exporter import export_pdf
from bot.exporters.audio_exporter import export_mp3
from bot.utils.logger import logger
from bot.utils.validators import validate_file
from bot.utils.status_tracker import StatusTracker
from exporters.pandoc_exporter import export_accessible_document
from config.settings import settings

router = Router()

OUTPUT_DIR = settings.temp_dir / "output"

user_modes: dict[int, str] = {}
user_emails: dict[int, str] = {}


async def _send_with_retry(
    bot,
    chat_id: int,
    msg: str,
    max_retries: int = 3,
) -> None:
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id, msg)
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


async def _send_doc_with_retry(
    message: Message,
    out_path: Path,
    caption: str,
    max_retries: int = 3,
) -> bool:
    for attempt in range(max_retries):
        try:
            await message.answer_document(
                document=FSInputFile(out_path),
                caption=caption,
            )
            return True
        except TelegramRetryAfter as e:
            wait = e.retry_after + attempt * 5
            logger.warning(
                "Telegram rate limit no envio de {}, aguardando {}s",
                out_path.name,
                wait,
            )
            await asyncio.sleep(wait)
    logger.error(
        "Falha apos {} tentativas para enviar {}",
        max_retries,
        out_path.name,
    )
    return False


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

    mode = user_modes.pop(message.chat.id, "normal")
    await message.answer("📄 Arquivo recebido!")
    await process_file(message, document.file_id, filename, mode=mode)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    photo: PhotoSize | None = message.photo[-1] if message.photo else None
    if photo is None:
        return

    mode = user_modes.pop(message.chat.id, "normal")
    await message.answer("📷 Foto recebida!")
    await process_file(message, photo.file_id, "imagem.png", mode=mode)


async def process_file(
    message: Message,
    file_id: str,
    filename: str,
    mode: str = "normal",
) -> None:
    tracker = StatusTracker(message.bot, message.chat.id, filename)

    with tempfile.TemporaryDirectory(dir=settings.temp_dir) as tmpdir:
        try:
            input_path = Path(tmpdir) / filename

            await tracker("Baixando arquivo...")
            await download_file(message.bot, file_id, input_path)

            canonical_document = await process(
                input_path,
                status_callback=tracker,
                mode=mode,
            )

            await tracker(
                "Conteudo extraido com sucesso! Preparando exportacao..."
            )

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            base_name = Path(filename).stem
            txt_path = OUTPUT_DIR / f"{base_name}.txt"
            docx_path = OUTPUT_DIR / f"{base_name}.docx"
            pdf_path = OUTPUT_DIR / f"{base_name}.pdf"
            html_path = OUTPUT_DIR / f"{base_name}.html"
            mp3_path = OUTPUT_DIR / f"{base_name}.mp3"

            export_txt(canonical_document, txt_path, filename)
            export_docx(canonical_document, docx_path, filename)
            export_pdf(canonical_document, pdf_path, filename)
            export_accessible_document(
                canonical_document,
                html_path,
                format_name="html",
                title=base_name,
                profile_name="html",
            )
            
            # Gera MP3 usando texto limpo do arquivo TXT com progresso fiel
            try:
                if txt_path.exists():
                    clean_text = txt_path.read_text(encoding="utf-8")
                    
                    async def audio_progress(percent: int):
                        await tracker(f"Gerando áudio (MP3)... {percent}%")
                    
                    await export_mp3(clean_text, mp3_path, progress_callback=audio_progress)
            except Exception as e:
                logger.error("Falha ao gerar MP3: {}", e)

            zip_path = OUTPUT_DIR / f"{base_name}_acessivel.zip"
            _build_zip_package(
                zip_path,
                [txt_path, docx_path, pdf_path, html_path, mp3_path],
            )

            # Verifica se há e-mail registrado para este chat
            target_email = user_emails.pop(message.chat.id, None)
            
            if target_email:
                await tracker(f"Enviando para e-mail: {target_email}...")
                from web.services.email_service import send_result_email
                await send_result_email(target_email, filename, zip_path)
                await message.answer(f"✅ Arquivo enviado para {target_email}!")
            else:
                await tracker("Enviando pacote acessivel...")
                caption = "Pacote acessivel gerado (.zip)."
                await _send_doc_with_retry(message, zip_path, caption)

            await tracker.finish(success=True)

        except TaskCancelledError:
            await tracker("Processamento cancelado.")
            await tracker.finish(success=False)
        except Exception:
            logger.exception("Erro ao processar arquivo")
            await tracker.finish(success=False)


def _build_zip_package(zip_path: Path, out_paths: list[Path]) -> None:
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for out_path in out_paths:
            if out_path.exists():
                archive.write(out_path, arcname=out_path.name)
