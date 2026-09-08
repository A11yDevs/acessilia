from datetime import datetime

import httpx
import shutil

from aiogram import Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import LOG_TELEGRAM_FEEDBACK_RECEIVED
from backend.services.cache import clear_cache
from backend.tools.logger import logger
from frontend.clients.api_client import ApiError
from frontend.clients import default_client
from frontend.telegram.handlers.document import user_modes, user_emails, user_task_ids
from frontend.telegram.middlewares.pause_middleware import get_paused_chats
from frontend.telegram.messages import (
    MSG_BOT_PAUSED,
    MSG_BOT_RESUMED,
    MSG_CACHE_CLEARED,
    MSG_CANCEL_NO_TASK,
    MSG_EMAIL_CONFIGURED,
    MSG_EMAIL_HINT,
    MSG_FEEDBACK_PROMPT,
    MSG_FEEDBACK_THANKS,
    MSG_FORMATS_TEXT,
    MSG_HELP_TEXT,
    MSG_HEALTH_ACTIVE_MODEL,
    MSG_HEALTH_DISK_FREE,
    MSG_HEALTH_TEMP_MISSING,
    MSG_HEALTH_TEMP_OK,
    MSG_MODE_BAIXO_ON,
    MSG_MODE_DETAILED_ON,
    MSG_MODE_MEDIO_ON,
    MSG_MODE_NORMAL_ON,
    MSG_MODE_OCR_ON,
    MSG_NO_TASK_REGISTERED,
    MSG_OLLAMA_OFFLINE,
    MSG_OLLAMA_ONLINE,
    MSG_OLLAMA_UNEXPECTED,
    MSG_START_TEXT,
    MSG_STATUS_SUMMARY,
    MSG_STATUS_TASK_NOT_FOUND,
    MSG_TASK_CANCEL_DONE,
    MSG_TASK_CANCEL_FAILED,
)

router = Router()

client = default_client


class FeedbackStates(StatesGroup):
    waiting_feedback = State()


@router.message(Command("email"))
async def cmd_email(message: Message) -> None:
    """Record the user's e-mail address from /email so processed files can be delivered there.

    Args:
        message (Message): Incoming aiogram ``/email`` command carrying the address argument to store, or none when only the bare command was sent; no default (required).
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(t(MSG_EMAIL_HINT))
        return

    email = args[1].strip()
    user_emails[(message.chat.id, message.message_thread_id)] = email
    await message.answer(t(MSG_EMAIL_CONFIGURED).format(email=email))


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Greet the user and summarize accepted formats via /start using the active locale's start-text string.

    Args:
        message (Message): Incoming aiogram /start command; no default (required).
    """
    await message.answer(t(MSG_START_TEXT))


@router.message(Command("ajuda"))
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """List every bot command available in the active locale via /ajuda or /help.

    Args:
        message (Message): Incoming aiogram help command; no default (required).
    """
    await message.answer(t(MSG_HELP_TEXT))


@router.message(Command("formatos"))
@router.message(Command("formats"))
async def cmd_formats(message: Message) -> None:
    """List accepted input containers and produced output formats via /formatos or its English alias /formats in the active locale.

    Args:
        message (Message): Incoming aiogram /formatos (or /formats) command; no default (required).
    """
    await message.answer(t(MSG_FORMATS_TEXT))


@router.message(Command("ocr"))
async def cmd_ocr(message: Message) -> None:
    """
    Activate text-only OCR extraction mode for this chat via /ocr so subsequent files skip visual description.

    Args:
        message (Message): Incoming aiogram /ocr command; no default (required).
    """
    user_modes[(message.chat.id, message.message_thread_id)] = "ocr"
    await message.answer(t(MSG_MODE_OCR_ON))


@router.message(Command("detalhado"))
@router.message(Command("detailed"))
async def cmd_detailed(message: Message) -> None:
    """
    Activate maximum-detail image+text description mode for this chat via /detalhado or its English alias /detailed.

    Args:
        message (Message): Incoming aiogram /detalhado (or /detailed) command; no default (required).
    """
    user_modes[(message.chat.id, message.message_thread_id)] = "detalhado"
    await message.answer(t(MSG_MODE_DETAILED_ON))


@router.message(Command("medio"))
@router.message(Command("medium"))
async def cmd_medium(message: Message) -> None:
    """
    Activate the default full-text + clear image description mode for this chat via /medio or its English alias /medium.

    Args:
        message (Message): Incoming aiogram /medio (or /medium) command; no default (required).
    """
    user_modes[(message.chat.id, message.message_thread_id)] = "medio"
    await message.answer(t(MSG_MODE_MEDIO_ON))


@router.message(Command("baixo"))
@router.message(Command("low"))
async def cmd_low(message: Message) -> None:
    """
    Activate content-focused fast mode for this chat via /baixo or its English alias /low (full text + concise image description only).

    Args:
        message (Message): Incoming aiogram /baixo (or /low) command; no default (required).
    """
    user_modes[(message.chat.id, message.message_thread_id)] = "baixo"
    await message.answer(t(MSG_MODE_BAIXO_ON))


@router.message(Command("normal"))
async def cmd_normal(message: Message) -> None:
    user_modes[(message.chat.id, message.message_thread_id)] = "medio"
    await message.answer(t(MSG_MODE_NORMAL_ON))


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """
    Show the current state of any processing task recorded for this chat, or a no-task notice when none exists.

    Args:
        message (Message): Incoming aiogram /status command; no default (required).
    """
    task_id = user_task_ids.get((message.chat.id, message.message_thread_id))
    if not task_id:
        await message.answer(t(MSG_NO_TASK_REGISTERED))
        return
    try:
        status = await client.get_job_status(task_id)
    except ApiError as e:
        await message.answer(t(MSG_STATUS_TASK_NOT_FOUND).format(status_code=e.status_code))
        return
    pct = int((status.get("progresso") or 0.0) * 100)
    status_icon = {
        "queued": "⏳",
        "processing": "⏳",
        "done": "✅",
        "error": "❌",
        "cancelled": "🚫",
    }.get(status.get("status", ""), "❓")
    await message.answer(
        t(MSG_STATUS_SUMMARY).format(
            icon=status_icon,
            task_id=task_id,
            filename=status.get('arquivo', '?'),
            pct=pct,
            stage=status.get('etapa_atual','')
        )
    )


@router.message(Command("health"))
async def cmd_health(message: Message) -> None:
    checks = []

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            tags_url = settings.ollama_base_url.replace("/api/chat", "/api/tags")
            r = await client.get(tags_url)
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name", "?") for m in data.get("models", [])]
                checks.append(t(MSG_OLLAMA_ONLINE).format(model_count=len(models)))
            else:
                checks.append(t(MSG_OLLAMA_UNEXPECTED).format(code=r.status_code))
    except Exception as e:
        checks.append(t(MSG_OLLAMA_OFFLINE).format(error=e))

    checks.append(t(MSG_HEALTH_ACTIVE_MODEL).format(model=settings.ollama_model))

    temp_dir = settings.temp_dir
    if temp_dir.exists():
        checks.append(t(MSG_HEALTH_TEMP_OK))
    else:
        checks.append(t(MSG_HEALTH_TEMP_MISSING))

    try:
        usage = shutil.disk_usage(temp_dir.anchor or "/")
        free_gb = usage.free / (1024**3)
        checks.append(t(MSG_HEALTH_DISK_FREE).format(free_gb=free_gb))
    except Exception:
        pass

    await message.answer("\n".join(checks))


@router.message(Command("limpar"))
@router.message(Command("clear"))
async def cmd_limpar(message: Message) -> None:
    """
    Clear the local cache directory of processed-file artifacts and confirm how many entries were removed.

    Args:
        message (Message): Incoming aiogram /limpar (or its English alias /clear) command; no default (required).
    """
    count = await clear_cache()
    await message.answer(t(MSG_CACHE_CLEARED).format(count=count))


@router.message(Command("cancelar"))
@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    """
    Cancel the currently tracked (if any) processing job for this chat and confirm or report failure.

    Args:
        message (Message): Incoming aiogram /cancelar (or its English alias /cancel) command; no default (required).
    """
    task_id = user_task_ids.get((message.chat.id, message.message_thread_id))
    if not task_id:
        await message.answer(t(MSG_CANCEL_NO_TASK))
        return
    try:
        result = await client.cancel_job(task_id)
    except ApiError as e:
        await message.answer(
            t(MSG_TASK_CANCEL_FAILED).format(status_code=e.status_code, detail=e.detail)
        )
        return
    user_task_ids.pop((message.chat.id, message.message_thread_id), None)
    cancelled_id = result.get('task_id', task_id)
    await message.answer(t(MSG_TASK_CANCEL_DONE).format(task_id=cancelled_id))


@router.message(Command("desativar"))
@router.message(Command("deactivate"))
async def cmd_desativar(message: Message) -> None:
    """
    Pause bot processing for this chat until /ativar or /activate is used again.

    Args:
        message (Message): Incoming aiogram /desativar (or its English alias /deactivate) command; no default (required).
    """
    paused = get_paused_chats()
    paused.add(message.chat.id)
    await message.answer(t(MSG_BOT_PAUSED))


@router.message(Command("ativar"))
@router.message(Command("activate"))
async def cmd_ativar(message: Message) -> None:
    """
    Resume bot processing for this chat after a prior /desativar or /deactivate pause.

    Args:
        message (Message): Incoming aiogram /ativar (or its English alias /activate) command; no default (required).
    """
    paused = get_paused_chats()
    paused.discard(message.chat.id)
    await message.answer(t(MSG_BOT_RESUMED))


@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    """
    Prompt the user to type their opinion of processing quality before entering a wait-for-text input state.

    Args:
        message (Message): Incoming aiogram /feedback command; no default (required).
        state (FSMContext): AIAGram FSM context used to transition into FeedbackStates.waiting_feedback after showing the prompt (no default, required aiogram-injected argument).
    """
    await state.set_state(FeedbackStates.waiting_feedback)
    await message.answer(t(MSG_FEEDBACK_PROMPT))


@router.message(StateFilter(FeedbackStates.waiting_feedback))
async def handle_feedback_text(message: Message, state: FSMContext) -> None:
    """Persist the user's free-text feedback to a local log file and acknowledge it.

    Args:
        message (Message): Aiogram Message holding the user's feedback text; no default (required).
        state (FSMContext): AIAGram FSM context that is cleared after the feedback is recorded (no default, aiogram-injected argument).
    """
    feedback = message.text or ""
    user = message.from_user
    user_info = f"{user.username or user.id}" if user else "unknown"

    logger.info(t(LOG_TELEGRAM_FEEDBACK_RECEIVED).format(
        user_info=user_info, feedback=feedback
    ))

    feedback_file = settings.temp_dir / "feedback.txt"
    feedback_file.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().isoformat()
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {user_info}: {feedback}\n")

    await state.clear()
    await message.answer(t(MSG_FEEDBACK_THANKS))
