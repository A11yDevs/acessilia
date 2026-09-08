"""VisionAgent — generation of accessible audio descriptions for images."""

import asyncio

from backend.i18n import t
from backend.log_messages import (
    LOG_VISION_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_SENDING_REGION,
)
from backend.tools.region_classifier import region_prompt_key
from backend.tools.logger import logger

from backend.tools.prompt_tools import build_page_prompt, load_region_prompt, load_system_prompt
from backend.ai.models.ai_client import get_agno_model
from agno.agent import Agent
from agno.media import Image


class VisionAgent:
    """Processes visual regions and produces accessible audio descriptions."""

    def __init__(self, mode: str = "medio") -> None:
        """Create a vision agent with a default prompting mode.

        Args:
            mode (str): Prompting mode name whose system prompt is loaded at construction (default "medio").
        """
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
        """Describe a single visual region of a page with the vision model.

        Args:
            image_bytes (bytes): PNG/encoded image payload of the region to describe.
            classification (str): Region classification key (e.g. "full_page_fallback", "full_page_image", or a region type) driving prompt selection.
            page_num (int): 1-based page number the region belongs to, used in log lines and page prompts (default 0).
            total_pages (int): Total page count of the source document for page prompts (default 0).
            mode (str | None): Prompting mode override for this call; falls back to the instance default when None (default None).
            custom_prompt (str | None): Fully custom prompt that, when given, replaces all selection logic (default None).

        Returns:
            str: The model's region description text, or an empty string when the vision call raised (the exception is logged as critical).
        """
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
                t(LOG_VISION_AGENT_SENDING_REGION).format(
                    page_num=page_num,
                    size=len(image_bytes),
                    type=classification,
                )
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
                t(LOG_VISION_AGENT_REGION_ERROR).format(
                    page_num=page_num,
                    type=classification,
                    error=error,
                    tb=tb,
                )
            )
            return ""
