"""DataAgent – Conversão de tabelas e fórmulas matemáticas em texto estruturado."""

import asyncio

from backend.i18n import t
from backend.log_messages import (
    LOG_DATA_AGENT_PROCESSING_REGION,
    LOG_DATA_AGENT_PROMPT_NOT_FOUND,
    LOG_DATA_AGENT_REGION_ERROR,
)
from backend.tools.logger import logger
from backend.tools.prompt_tools import load_region_prompt
from backend.ai.models.ai_client import get_agno_model
from agno.agent import Agent
from agno.media import Image


# Region classification to region prompt key mapping.
DATA_PROMPT_KEY_MAP = {
    "table": "regiao_tabela",
    "formula": "regiao_formula",
}


class DataAgent:
    """Processa regiões de tabelas e fórmulas usando IA de visão."""

    async def process_region(
        self,
        image_bytes: bytes,
        classification: str,
        page_num: int = 0,
        fallback_text: str = "",
    ) -> str:
        """Processa uma região de tabela ou fórmula."""
        prompt_key = DATA_PROMPT_KEY_MAP.get(classification, "")
        prompt = load_region_prompt(prompt_key)

        if not prompt:
            logger.warning(
                t(LOG_DATA_AGENT_PROMPT_NOT_FOUND).format(
                    page_num=page_num,
                    type=classification,
                )
            )
            return fallback_text

        try:
            logger.debug(
                t(LOG_DATA_AGENT_PROCESSING_REGION).format(
                    page_num=page_num,
                    size=len(image_bytes),
                    type=classification,
                )
            )

            agent = Agent(
                name="DataAgent",
                model=get_agno_model(),
                telemetry=False,
            )

            def _run_data():
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

            return (await asyncio.to_thread(_run_data)).strip()

        except Exception as error:
            import traceback
            tb = traceback.format_exc()
            logger.critical(
                t(LOG_DATA_AGENT_REGION_ERROR).format(
                    page_num=page_num,
                    type=classification,
                    error=error,
                    tb=tb,
                )
            )
            return fallback_text
