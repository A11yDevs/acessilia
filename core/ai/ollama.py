import asyncio
import base64
import httpx
from typing import Optional
from core.utils.logger import logger
from config.settings import settings


class OllamaClient:
    def __init__(self):
        self.api_key = settings.ollama_api_key
        self.model = settings.ollama_model
        self.base_url = settings.ollama_base_url
        self.timeout = settings.request_timeout
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
            ),
        )

    async def send_message(
        self,
        text: str,
        images: Optional[list[bytes]] = None,
        max_retries: int = 5,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("OLLAMA_API_KEY nao configurada")

        message: dict = {"role": "user", "content": text}
        if images:
            message["images"] = [
                base64.b64encode(img_bytes).decode("utf-8") for img_bytes in images
            ]

        payload = {
            "model": self.model,
            "messages": [message],
            "stream": False,
            "options": {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 64,
                "vision_budget": 560,
                "seed": 42,
            },
            "keep_alive": -1,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(max_retries):
            try:
                logger.debug(
                    "Enviando requisição para Ollama (tentativa {}/{}): "
                    "modelo={}, image_count={}",
                    attempt + 1,
                    max_retries,
                    self.model,
                    len(images or []),
                )
                response = await self._client.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                )

                if response.status_code in (429, 502, 503, 504):
                    delay = (2**attempt) + 2
                    logger.warning(
                        "Ollama erro temporário ({}), aguardando {}s...",
                        response.status_code,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code != 200:
                    error_text = response.text
                    logger.error(
                        "Ollama error ({}): {}",
                        response.status_code,
                        error_text,
                    )

                response.raise_for_status()
                data = response.json()

                message = data.get("message") or {}
                result = (message.get("content") or "").strip()

                done_reason = data.get("done_reason")

                if done_reason == "length":
                    logger.warning(
                        "IA cortou a resposta por tamanho (length). "
                        "Tentando novamente..."
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                        continue

                if result:
                    return result

                logger.warning(
                    "Ollama respondeu vazio (tentativa {}/{})",
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)

            except Exception as e:
                logger.error(
                    "Ollama error (tentativa {}/{}): {}",
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    delay = (2**attempt) + 1
                    await asyncio.sleep(delay)
                else:
                    raise

        return "[Erro: Ollama falhou após todas as tentativas de recuperação]"

    def reset_session(self):
        pass

    async def close(self):
        await self._client.aclose()


client = OllamaClient()
