import asyncio
import base64
import httpx
from typing import Optional
from core.utils.logger import logger
from config.settings import settings


class OpenRouterClient:

    def __init__(self):
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.base_url = settings.openrouter_base_url
        self.timeout = settings.request_timeout

    async def send_message(
        self,
        text: str,
        images: Optional[list[bytes]] = None,
        max_retries: int = 5,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY nao configurada")

        messages = []
        content = []

        if images:
            for img_bytes in images:
                b64_image = base64.b64encode(img_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64_image}"
                    }
                })

        content.append({
            "type": "text",
            "text": text
        })

        messages.append({
            "role": "user",
            "content": content
        })

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "seed": 42,
            "max_tokens": 4096,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/bot-acess",
            "X-Title": "Bot Acess Accessibility",
            "Content-Type": "application/json"
        }

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug(
                        "Enviando requisicao para OpenRouter (tentativa {}/{}): "
                        "modelo={}, image_count={}",
                        attempt + 1, max_retries, self.model, len(images or [])
                    )
                    response = await client.post(
                        self.base_url,
                        json=payload,
                        headers=headers
                    )

                    if response.status_code in (429, 502, 503, 504):
                        delay = (2 ** attempt) + 2
                        logger.warning(
                            "OpenRouter erro temporario ({}), aguardando {}s...",
                            response.status_code, delay
                        )
                        await asyncio.sleep(delay)
                        continue

                    if response.status_code != 200:
                        error_text = response.text
                        logger.error(
                            "OpenRouter error ({}): {}",
                            response.status_code, error_text
                        )

                    response.raise_for_status()
                    data = response.json()

                    choices = data.get("choices", [])
                    if not choices:
                        logger.warning(
                            "OpenRouter retornou resposta sem choices "
                            "(tentativa {}/{}): {}",
                            attempt + 1, max_retries, data
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        return "[Erro: OpenRouter retornou resposta sem conteudo]"

                    choice = choices[0]
                    finish_reason = choice.get("finish_reason")
                    message = choice.get("message") or {}
                    content = message.get("content")

                    if isinstance(content, str):
                        result = content.strip()
                    elif isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                part_text = part.get("text")
                                if isinstance(part_text, str):
                                    text_parts.append(part_text)
                        result = "\n".join(text_parts).strip()
                    else:
                        result = ""

                    if finish_reason == "length":
                        logger.warning(
                            "OpenRouter cortou a resposta por tamanho (length). "
                            "Tentando novamente..."
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue

                    if result:
                        return result

                    logger.warning(
                        "OpenRouter respondeu vazio (tentativa {}/{})",
                        attempt + 1, max_retries
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)

            except Exception as e:
                logger.error(
                    "OpenRouter error (tentativa {}/{}): {}",
                    attempt + 1, max_retries, e
                )
                if attempt < max_retries - 1:
                    delay = (2 ** attempt) + 1
                    await asyncio.sleep(delay)
                else:
                    raise

        return "[Erro: OpenRouter falhou apos todas as tentativas de recuperacao]"

    def reset_session(self):
        pass


client = OpenRouterClient()
