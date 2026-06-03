from typing import Optional, Protocol


class AIClient(Protocol):
    async def send_message(
        self,
        text: str,
        images: Optional[list[bytes]] = None,
    ) -> str: ...
