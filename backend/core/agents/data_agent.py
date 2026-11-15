"""DataAgent: validated extraction of tables and mathematical formulas.

Each call has a hard deadline and no implicit OpenAI SDK retries. A transient
transport error follows the existing degradation path; the table stage's
reread and retry-pass budgets remain separate from this per-call bound.

Abandoning the await does not stop the thread: it retains its connection and
per-call Agent/model client until the provider finishes or the process stops.
The application supplies a shared runner with bounded admission; abandoned
calls retain its capacity, independently of transient event loops (#276).
"""

from backend.core.i18n import t
from backend.core.i18n.log_messages import (
    LOG_DATA_AGENT_PROCESSING_REGION,
    LOG_DATA_AGENT_PROMPT_NOT_FOUND,
    LOG_DATA_AGENT_REGION_ERROR,
)
from backend.core.logger import logger
from backend.core.agents.prompt_tools import load_region_prompt
from backend.core.agents.ai_client import get_agno_model
from backend.core.agents.model_call_policy import model_call_deadline
from backend.core.agents.model_calls import ModelCallRunner, current_model_calls
from backend.core.config import ModelConfig, ToolboxConfig
from backend.core.agents.output_schemas import (
    DATA_SCHEMA_INSTRUCTION,
    DataOutput,
    validate_structured_run,
)
from agno.agent import Agent
from agno.media import Image


# Region classification to region prompt key mapping.
DATA_PROMPT_KEY_MAP = {
    "table": "regiao_tabela",
    "formula": "regiao_formula",
}


class DataAgent:
    """Processes table and formula regions with a vision model."""

    def __init__(
        self, *, models: ModelConfig, toolbox: ToolboxConfig,
        model_calls: ModelCallRunner | None = None,
    ) -> None:
        """The run's model configuration (``ModelConfig``: client, budgets, timeout)
        and its Toolbox (the gateway with ``ai_client == "toolbox"``)."""
        self.models = models
        self.toolbox = toolbox
        self.model_calls = model_calls if model_calls is not None else current_model_calls()

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

            timeout_seconds = self.models.data_agent_timeout_seconds
            agent = Agent(
                name="DataAgent",
                model=get_agno_model(
                    self.models,
                    self.toolbox,
                    max_tokens=(
                        self.models.data_agent_max_tokens
                        if classification == "table"
                        else None
                    ),
                    timeout_seconds=timeout_seconds,
                    max_retries=0,
                ),
                output_schema=DataOutput,
                telemetry=False,
            )

            def _run_data():
                return agent.run(
                    input=prompt,
                    images=[Image(content=image_bytes)],
                )

            response = await self.model_calls.run(
                _run_data, timeout=model_call_deadline(timeout_seconds),
                label=f"DataAgent/{classification}/page-{page_num}",
            )
            result = validate_structured_run(response, DataOutput)
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
