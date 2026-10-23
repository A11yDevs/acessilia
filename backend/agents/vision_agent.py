"""VisionAgent — generation of accessible audio descriptions for images."""

import asyncio
import functools

from pydantic import ValidationError

from backend.i18n import t
from backend.log_messages import (
    LOG_VISION_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_REGION_RECOVERED,
    LOG_VISION_AGENT_REGION_RETRY,
    LOG_VISION_AGENT_SENDING_REGION,
)
from backend.tools.region_classifier import region_prompt_key
from backend.tools.logger import logger

from backend.tools.prompt_tools import build_page_prompt, load_region_prompt, load_system_prompt
from backend.ai.models.ai_client import get_agno_model
from backend.agents.output_schemas import (
    PAGE_INSPECTION_INSTRUCTION,
    VISION_SCHEMA_INSTRUCTION,
    OutputModel,
    PageInspectionOutput,
    VisionOutput,
    validate_structured_run,
)
from agno.agent import Agent
from agno.media import Image

#: Tries per region or page. Sampled models sometimes fall into a repetition
#: loop (the same LaTeX token over and over in a formula) until max_tokens cuts
#: the JSON off, and an image left undescribed fails the whole document
#: (``describe-image`` and ``inspect-unstructured-pages`` are critical, and
#: ``describe-image`` has no other vision method to fall back to).
#:
#: Only an answer that fails schema validation is retried; timeouts, provider
#: errors and incomplete runs fail at once, since repeating them without
#: backoff costs up to another REQUEST_TIMEOUT and doubles the load.
#:
#: This retry is deliberately kept instead of tuning temperature or repetition
#: penalties: changing those affects every answer and needs measuring first,
#: which the recovery INFO log makes possible. With Ollama the seed is fixed
#: (``get_agno_model``), so the retry differs from the first try only by
#: RETRY_INSTRUCTION; that changes the prompt and therefore the sampled tokens,
#: but a loop that does not depend on the prompt will still fail twice.
REGION_ATTEMPTS = 2

#: Appended to the prompt of a retry. Each try is a fresh Agent with no
#: history, so it is phrased as a plain instruction, not as feedback on an
#: answer the model never saw; and it asks for no padding rather than for
#: brevity, since a long formula must still be transcribed whole.
RETRY_INSTRUCTION = (
    "Responda com um objeto JSON completo e válido, fechando todas as strings e "
    "chaves. Não repita tokens nem preencha campos com repetições ou espaços."
)


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
    ) -> VisionOutput | None:
        """Describe a single visual region of a page with the vision model.

        Args:
            image_bytes (bytes): PNG/encoded image payload of the region to describe.
            classification (str): Region classification key (e.g. "full_page_fallback", "full_page_image", or a region type) driving prompt selection.
            page_num (int): 1-based page number the region belongs to, used in log lines and page prompts (default 0).
            total_pages (int): Total page count of the source document for page prompts (default 0).
            mode (str | None): Prompting mode override for this call; falls back to the instance default when None (default None).
            custom_prompt (str | None): Fully custom prompt that, when given, replaces all selection logic (default None).

        Returns:
            A validated visual result, or None when inference or validation fails.
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

        prompt = f"{prompt}\n\n{VISION_SCHEMA_INSTRUCTION}"

        try:
            return await _run_with_retry(
                prompt, image_bytes, VisionOutput, page_num=page_num, label=classification
            )
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
            return None

    async def inspect_page(
        self,
        image_bytes: bytes,
        page_num: int,
        total_pages: int,
    ) -> PageInspectionOutput:
        """Decide whether a page without extracted structure is blank, or describe it.

        Unlike :meth:`describe_region`, a failure is raised instead of returning
        None: the caller records it as a failed planning method, so the job
        does not silently lose the page.
        """
        prompt = (
            f"{build_page_prompt(self.system_prompt, total_pages, page_num, is_pdf=total_pages > 1)}"
            f"\n\n{PAGE_INSPECTION_INSTRUCTION}"
        )
        return await _run_with_retry(
            prompt, image_bytes, PageInspectionOutput, page_num=page_num, label="page_inspection"
        )


async def _run_with_retry(
    prompt: str,
    image_bytes: bytes,
    schema: type[OutputModel],
    *,
    page_num: int,
    label: str,
) -> OutputModel:
    """Ask the vision model for ``schema``, retrying an answer that fails validation.

    Raises the last validation error when every attempt fails, and any other
    error (timeout, provider failure, incomplete run) at once.
    """
    for attempt in range(1, REGION_ATTEMPTS + 1):
        attempt_prompt = prompt if attempt == 1 else f"{prompt}\n\n{RETRY_INSTRUCTION}"
        logger.debug(
            t(LOG_VISION_AGENT_SENDING_REGION).format(
                page_num=page_num,
                size=len(image_bytes),
                type=label,
            )
        )
        agent = Agent(
            name="VisionAgent",
            model=get_agno_model(),
            output_schema=schema,
            telemetry=False,
        )
        run = functools.partial(
            agent.run, input=attempt_prompt, images=[Image(content=image_bytes)]
        )
        response = await asyncio.to_thread(run)
        try:
            output = validate_structured_run(response, schema)
        except ValidationError as error:
            if attempt == REGION_ATTEMPTS:
                raise
            logger.warning(
                t(LOG_VISION_AGENT_REGION_RETRY).format(
                    page_num=page_num,
                    type=label,
                    attempt=attempt + 1,
                    attempts=REGION_ATTEMPTS,
                    error=_short_error(error),
                )
            )
            continue
        if attempt > 1:
            logger.info(
                t(LOG_VISION_AGENT_REGION_RECOVERED).format(
                    page_num=page_num,
                    type=label,
                    attempt=attempt,
                    attempts=REGION_ATTEMPTS,
                )
            )
        return output
    raise AssertionError("REGION_ATTEMPTS must be at least 1")


def _short_error(error: ValidationError, limit: int = 300) -> str:
    """The causes of a validation error on one line, without the rejected answer.

    ``str(error)`` starts with a bare header ("1 validation error for ...") and
    embeds the answer itself, which can be 10 kB long.
    """
    causes = "; ".join(
        f"{'.'.join(map(str, item['loc']))}: {item['msg']}" if item["loc"] else item["msg"]
        for item in error.errors(include_url=False, include_input=False)
    )
    text = " ".join(causes.split()) or type(error).__name__
    return text if len(text) <= limit else f"{text[:limit]}…"
