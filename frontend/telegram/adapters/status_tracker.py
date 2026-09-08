import re
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from backend.i18n import t
from backend.log_messages import (
    LOG_STATUS_EDIT_UNEXPECTED,
    LOG_STATUS_MESSAGE_EDIT_FAILED,
    LOG_STATUS_MESSAGE_SEND_FAILED,
)
from backend.tools.logger import logger
from frontend.telegram.messages import (
    MSG_STATUS_CONVERSION_DONE,
    MSG_STATUS_PROCESSING_FAILED,
)



class StatusTracker:
    """Edits a single live progress message in the chat as the job advances.

    Args:
        bot (Bot): Aiogram Bot instance used for sending and editing messages; no default (required).
        chat_id (int): Numeric chat id the live message lives in; no default (required).
        filename (str): Source filename shown in the message header; no default (required).
        message_thread_id (int | None): Forum-topic thread id to scope the message to, or None for top-level chats (default: None).
    """

    def __init__(self, bot: Bot, chat_id: int, filename: str, message_thread_id: int | None = None):
        self.bot = bot
        self.chat_id = chat_id
        self.filename = filename
        self.message_thread_id = message_thread_id
        self.message_id: int | None = None
        self._last_text: str = ""

    def _build_progress_bar(self, percent: int, width: int = 20) -> str:
        """Assemble a text-based progress bar like ``[████░░░░░░] 40%``.

        Args:
            percent (int): Completion percentage between 0 and 100.
            width (int): Total bar cell count to render (default: 20).

        Returns:
            str: Bracketed bar filled proportionally to ``percent`` followed by the percentage number.
        """
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percent}%"

    def _format_message(self, msg: str) -> str:
        """Render one localized stage label into its decorated chat form.

        Appends a progress bar when the stage carries a parseable page count
        (in any active locale form) or an audio-generation percentage, and
        otherwise picks the most fitting header emoji from bilingual keyword
        hints (Portuguese and English) so both locales render consistently.

        Args:
            msg (str): Localized pipeline stage label received from the job status stream; no default (required).

        Returns:
            str: Markdown-formatted message with filename header, optional progress bar and localized stage text.
        """
        match = re.search(r"(?:pagina|página|page)\s*(\d+)\s*(?:de|of)\s*(\d+)", msg, re.IGNORECASE)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            percent = int((current / total) * 100)
            bar = self._build_progress_bar(percent)
            return f"📄 *{self.filename}*\n\n{msg}\n{bar}"

        audio_match = re.search(r"(?:Gerando áudio|spoken audio).*?(\d+)%", msg, re.IGNORECASE)
        if audio_match:
            percent = int(audio_match.group(1))
            bar = self._build_progress_bar(percent)
            return f"📄 *{self.filename}*\n\n{msg}\n{bar}"

        keywords = {
            "baixando": "⬇️",
            "downloading": "⬇️",
            "analisando": "🔍",
            "analyzing": "🔍",
            "separando": "✂️",
            "splitting": "✂️",
            "preparando": "⚙️",
            "preparing": "⚙️",
            "extraido": "✅",
            "exportando": "📝",
            "exporting": "📝",
            "gerando": "📝",
            "generating": "📝",
            "enviando": "📤",
            "sending": "📤",
            "concluida": "✅",
            "concluída": "✅",
            "completed": "✅",
            "finished": "✅",
            "cancelado": "🚫",
            "cancelled": "🚫",
            "erro": "❌",
            "error": "❌",
            "failed": "❌",
            "falha": "❌",
            "failure": "❌",
            "aguardando": "⏳",
            "queued": "⏳",
            "waiting": "⏳",
            "fila": "⏳",
        }

        header = "📄"
        lower = msg.lower()
        for keyword, emoji in keywords.items():
            if keyword in lower:
                header = emoji
                break

        return f"📄 *{self.filename}*\n\n{header} {msg}"

    async def __call__(self, msg: str) -> None:
        """Send the progress message once, or edit it in place for later stage updates.

        Args:
            msg (str): Localized stage label to surface in the live message; no default (required).
        """
        text = self._format_message(msg)
        self._last_text = text

        if self.message_id is None:
            try:
                sent = await self.bot.send_message(
                    self.chat_id, text, parse_mode="Markdown",
                    message_thread_id=self.message_thread_id,
                )
                self.message_id = sent.message_id
            except Exception as e:
                logger.warning(
                    t(LOG_STATUS_MESSAGE_SEND_FAILED).format(error=e)
                )
                try:
                    sent = await self.bot.send_message(
                        self.chat_id, msg,
                        message_thread_id=self.message_thread_id,
                    )
                    self.message_id = sent.message_id
                except Exception:
                    pass
        else:
            try:
                await self.bot.edit_message_text(
                    text,
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    parse_mode="Markdown",
                )
            except TelegramAPIError as e:
                logger.debug(
                    t(LOG_STATUS_MESSAGE_EDIT_FAILED).format(error=e)
                )
            except Exception as e:
                logger.warning(
                    t(LOG_STATUS_EDIT_UNEXPECTED).format(error=e)
                )

    async def finish(self, success: bool = True) -> None:
        """Replace the live message with a localized success or failure final receipt.

        Args:
            success (bool): True edits in a completion receipt, False a processing-failure receipt (default: True).
        """
        if self.message_id is None:
            return
        try:
            if success:
                text = (
                    f"📄 *{self.filename}*\n\n"
                    f"{t(MSG_STATUS_CONVERSION_DONE)}"
                )
            else:
                text = (
                    f"📄 *{self.filename}*\n\n"
                    f"{t(MSG_STATUS_PROCESSING_FAILED)}"
                )
            await self.bot.edit_message_text(
                text,
                chat_id=self.chat_id,
                message_id=self.message_id,
                parse_mode="Markdown",
            )
        except Exception:
            pass
