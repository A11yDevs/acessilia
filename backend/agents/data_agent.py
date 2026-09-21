"""DataAgent – Extração validada de tabelas e fórmulas matemáticas."""

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
from backend.agents.output_schemas import (
    DATA_SCHEMA_INSTRUCTION,
    DataOutput,
    validate_structured_content,
)
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
    ) -> DataOutput | None:
        """Extract a table or formula into a validated Pydantic model.

        ``fallback_text`` remains in the public signature for compatibility;
        the orchestrator applies that trusted extractor text only when this
        method returns ``None``.
        """
        prompt_key = DATA_PROMPT_KEY_MAP.get(classification, "")
        prompt = load_region_prompt(prompt_key)

        if not prompt:
            logger.warning(
                t(LOG_DATA_AGENT_PROMPT_NOT_FOUND).format(
                    page_num=page_num,
                    type=classification,
                )
            )
            return None

        prompt = f"{prompt}\n\n{DATA_SCHEMA_INSTRUCTION}"

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
                output_schema=DataOutput,
                telemetry=False,
            )

            def _run_data():
                return agent.run(
                    input=prompt,
                    images=[Image(content=image_bytes)],
                ).content

            content = await asyncio.to_thread(_run_data)
            result = validate_structured_content(content, DataOutput)
            if result.kind != classification:
                raise ValueError(
                    f"DataAgent returned kind={result.kind!r} for classification={classification!r}"
                )
            return result

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
            return None
