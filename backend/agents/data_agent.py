"""DataAgent – Conversão de tabelas e fórmulas matemáticas em texto estruturado."""

from backend.tools.logger import logger
from backend.tools.prompt_tools import load_region_prompt
from backend.ai.models.ai_client import get_agno_model
from agno.agent import Agent
from agno.media import Image


# Mapeamento de classificação → chave de prompt de região
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
                "[pag {}] Prompt nao encontrado para tipo={}, usando fallback",
                page_num,
                classification,
            )
            return fallback_text

        try:
            logger.debug(
                "[pag {}] DataAgent processando regiao ({} bytes, tipo={})",
                page_num,
                len(image_bytes),
                classification,
            )

            agent = Agent(
                name="DataAgent",
                model=get_agno_model(),
                telemetry=False,
            )

            response = await agent.arun(
                input=prompt,
                images=[Image(content=image_bytes)],
            )

            return response.content.strip()

        except Exception as error:
            import traceback
            tb = traceback.format_exc()
            logger.critical(
                "[pag {}] DataAgent erro na regiao {}: {} | Traceback:\n{}",
                page_num,
                classification,
                error,
                tb,
            )
            return fallback_text
