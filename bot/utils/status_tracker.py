import re
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from bot.utils.logger import logger


class StatusTracker:
    def __init__(self, bot: Bot, chat_id: int, filename: str):
        self.bot = bot
        self.chat_id = chat_id
        self.filename = filename
        self.message_id: int | None = None
        self._last_text: str = ""

    def _build_progress_bar(self, percent: int, width: int = 20) -> str:
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percent}%"

    def _format_message(self, msg: str) -> str:
        # Padrão para páginas
        match = re.search(r"pagina (\d+) de (\d+)", msg, re.IGNORECASE)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            percent = int((current / total) * 100)
            bar = self._build_progress_bar(percent)
            return f"📄 *{self.filename}*\n\n{msg}\n{bar}"
        
        # Padrão para áudio (ex: "Gerando áudio (MP3)... 50%")
        audio_match = re.search(r"Gerando áudio.* (\d+)%", msg, re.IGNORECASE)
        if audio_match:
            percent = int(audio_match.group(1))
            bar = self._build_progress_bar(percent)
            return f"📄 *{self.filename}*\n\n{msg}\n{bar}"

        keywords = {
            "baixando": "⬇️",
            "analisando": "🔍",
            "separando": "✂️",
            "preparando": "⚙️",
            "extraido": "✅",
            "gerando": "📝",
            "enviando": "📤",
            "concluida": "✅",
            "cancelado": "🚫",
            "erro": "❌",
        }

        header = "📄"
        lower = msg.lower()
        for keyword, emoji in keywords.items():
            if keyword in lower:
                header = emoji
                break

        return f"📄 *{self.filename}*\n\n{header} {msg}"

    async def __call__(self, msg: str) -> None:
        text = self._format_message(msg)
        self._last_text = text

        if self.message_id is None:
            try:
                sent = await self.bot.send_message(
                    self.chat_id, text, parse_mode="Markdown"
                )
                self.message_id = sent.message_id
            except Exception as e:
                logger.warning("Falha ao enviar mensagem de status: {}", e)
                try:
                    sent = await self.bot.send_message(self.chat_id, msg)
                    self.message_id = sent.message_id
                except Exception:
                    pass
        else:
            try:
                await self.bot.edit_message_text(
                    text, chat_id=self.chat_id, message_id=self.message_id, parse_mode="Markdown"
                )
            except TelegramAPIError as e:
                logger.debug("Falha ao editar mensagem de status: {}", e)
            except Exception as e:
                logger.warning("Erro inesperado ao editar status: {}", e)

    async def finish(self, success: bool = True) -> None:
        if self.message_id is None:
            return
        try:
            if success:
                text = f"📄 *{self.filename}*\n\n✅ Conversao concluida!"
            else:
                text = f"📄 *{self.filename}*\n\n❌ Erro no processamento."
            await self.bot.edit_message_text(
                text, chat_id=self.chat_id, message_id=self.message_id, parse_mode="Markdown"
            )
        except Exception:
            pass
