import asyncio
import base64
from typing import Optional

import httpx

from bot.utils.logger import logger
from config.settings import settings


class OpenRouterClient:
    """Cliente para a API do OpenRouter (compatível com Chat Completions)."""

    def __init__(self):
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.timeout = settings.request_timeout
        self.site_url = settings.openrouter_site_url
        self.app_name = settings.openrouter_app_name

    async def send_message(
        self,
        text: str,
        images: Optional[list[bytes]] = None,
        max_retries: int = 5,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY nao configurada")

        content = []
        if images:
            for img_bytes in images:
                b64_image = base64.b64encode(img_bytes).decode("utf-8")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}",
                        },
                    }
                )

        content.append({"type": "text", "text": text})

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": settings.openrouter_max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name

        endpoint = f"{self.base_url}/chat/completions"

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug(
                        "Enviando requisicao para OpenRouter "
                        "(tentativa {}/{}): modelo={}, image_count={}",
                        attempt + 1,
                        max_retries,
                        self.model,
                        len(images or []),
                    )
                    response = await client.post(
                        endpoint,
                        json=payload,
                        headers=headers,
                    )

                    if response.status_code in (429, 502, 503, 504):
                        delay = (2**attempt) + 2
                        logger.warning(
                            "OpenRouter erro temporario ({}), "
                            "aguardando {}s...",
                            response.status_code,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue

                    if response.status_code != 200:
                        logger.error(
                            "OpenRouter error ({}): {}",
                            response.status_code,
                            response.text,
                        )

                    response.raise_for_status()
                    data = response.json()

                    choices = data.get("choices", [])
                    if not choices:
                        logger.warning(
                            "OpenRouter retornou resposta sem choices "
                            "(tentativa {}/{}): {}",
                            attempt + 1,
                            max_retries,
                            data,
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        return (
                            "[Erro: OpenRouter retornou resposta "
                            "sem conteudo]"
                        )

                    message = choices[0].get("message") or {}
                    result = (message.get("content") or "").strip()

                    if result:
                        return result

                    logger.warning(
                        "OpenRouter respondeu vazio (tentativa {}/{})",
                        attempt + 1,
                        max_retries,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)

            except Exception as e:
                logger.error(
                    "OpenRouter error (tentativa {}/{}): {}",
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    delay = (2**attempt) + 1
                    await asyncio.sleep(delay)
                else:
                    raise

        return (
            "[Erro: OpenRouter falhou apos todas as "
            "tentativas de recuperacao]"
        )

    def reset_session(self):
        # Cliente stateless
        pass


client = OpenRouterClient()
