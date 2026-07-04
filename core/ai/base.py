"""Base abstract class for LLM clients used in the bot.

All concrete LLM clients (e.g., OllamaClient, OpenRouterClient) must inherit
from :class:`BaseLLMClient` and implement :meth:`send_message`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMClient(ABC):
    """Interface mínima que todo cliente de modelo de linguagem deve implementar.

    * ``send_message`` – envia um *prompt* (e opcionalmente outros parâmetros)
      e devolve a resposta textual.
    * ``reset_session`` – opcional, limpa o estado interno da sessão.
    * ``close`` – opcional, fecha recursos de rede.
    """

    @abstractmethod
    async def send_message(self, prompt: str, **kwargs: Any) -> str:
        """Enviar um prompt ao modelo e receber a resposta.

        Args:
            prompt: Texto a ser processado pelo modelo.
            **kwargs: Parâmetros específicos do provedor (por ex., ``images``).
        """
        raise NotImplementedError

    async def reset_session(self) -> None:
        """Resetar o estado da sessão, caso o cliente a mantenha.
        Implementações concretas podem sobrescrever este método.
        """
        return None

    async def close(self) -> None:
        """Fechar recursos (conexões HTTP, sockets, etc.)."""
        return None
