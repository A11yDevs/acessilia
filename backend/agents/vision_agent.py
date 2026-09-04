"""VisionAgent – Geração de audiodescrições acessíveis de imagens."""

import asyncio

from backend.tools.region_classifier import region_prompt_key
from backend.tools.logger import logger

from backend.tools.prompt_tools import build_page_prompt, load_region_prompt, load_system_prompt
from backend.ai.models.ai_client import get_agno_model
from agno.agent import Agent
from agno.media import Image


class VisionAgent:
    """Processa regiões visuais e produz audiodescrições acessíveis."""

    def __init__(self, mode: str = "medio"):
        self.mode = mode
        self.system_prompt = load_system_prompt(mode)

    async def describe_region(
        self,
        image_bytes: bytes,
        classification: str,
        page_num: int = 0,
        total_pages: int = 0,
        mode: str | None = None,
        custom_prompt: str | None = None,
    ) -> str:
        """Descreve uma região visual usando IA de visão."""
        effective_mode = mode or self.mode

        if custom_prompt:
            prompt = custom_prompt
        elif classification == "full_page_fallback":
            base = load_system_prompt(effective_mode)
            prompt = build_page_prompt(base, total_pages, page_num, is_pdf=True)
        elif classification == "full_page_image":
            base = load_system_prompt(effective_mode)
            prompt = build_page_prompt(base, total_pages, page_num, is_pdf=False)
        else:
            prompt_key = region_prompt_key(classification)
            region_prompt = load_region_prompt(prompt_key)
            prompt = region_prompt if region_prompt else self.system_prompt

        try:
            logger.debug(
                "[pag {}] Enviando regiao para visao ({} bytes, tipo={})",
                page_num,
                len(image_bytes),
                classification,
            )

            agent = Agent(
                name="VisionAgent",
                model=get_agno_model(),
                telemetry=False,
            )

            def _run_vision():
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(
                        agent.arun(
                            input=prompt,
                            images=[Image(content=image_bytes)],
                        )
                    ).content
                finally:
                    loop.close()

            return (await asyncio.to_thread(_run_vision)).strip()

        except Exception as error:
            import traceback
            tb = traceback.format_exc()
            logger.critical(
                "[pag {}] Erro na regiao {}: {} | Traceback:\n{}",
                page_num,
                classification,
                error,
                tb,
            )
            return ""
