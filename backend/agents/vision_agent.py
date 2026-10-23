"""VisionAgent — generation of accessible audio descriptions for images."""

import asyncio
import functools
import json
import re

from docstruct.fusion.repetition import collapse
from pydantic import ValidationError

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import (
    LOG_VISION_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_REGION_RECOVERED,
    LOG_VISION_AGENT_REGION_RETRY,
    LOG_VISION_AGENT_REGION_SALVAGED,
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
#: the JSON off. An image left undescribed is exported with a generic alt text
#: (``describe-image`` is non-critical); an unstructured page left uninspected
#: still fails the document (``inspect-unstructured-pages`` is critical).
#: When every try is cut off, ``_salvage_truncated_description`` recovers the
#: description from the last one if it got that far.
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
        full_budget: bool = False,
    ) -> VisionOutput | None:
        """Describe a single visual region of a page with the vision model.

        Args:
            image_bytes (bytes): PNG/encoded image payload of the region to describe.
            classification (str): Region classification key (e.g. "full_page_fallback", "full_page_image", or a region type) driving prompt selection.
            page_num (int): 1-based page number the region belongs to, used in log lines and page prompts (default 0).
            total_pages (int): Total page count of the source document for page prompts (default 0).
            mode (str | None): Prompting mode override for this call; falls back to the instance default when None (default None).
            custom_prompt (str | None): Fully custom prompt that, when given, replaces all selection logic (default None).
            full_budget (bool): Use the general token budget instead of VISION_REGION_MAX_TOKENS, for a region that may need transcribing (default False).

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
        # A whole page, or a region inspected for review-structure (scanned text,
        # a table), may need the general budget to be transcribed; a picture
        # gets the smaller one, which also bounds what a degenerate try costs.
        max_tokens = (
            None
            if full_budget or classification.startswith("full_page")
            else settings.vision_region_max_tokens
        )

        try:
            return await _run_with_retry(
                prompt, image_bytes, VisionOutput, page_num=page_num, label=classification,
                max_tokens=max_tokens,
            )
        except Exception as error:
            salvaged = (
                _salvage_truncated_description(error)
                if isinstance(error, ValidationError)
                else None
            )
            if salvaged is not None:
                logger.warning(
                    t(LOG_VISION_AGENT_REGION_SALVAGED).format(
                        page_num=page_num,
                        type=classification,
                        chars=len(salvaged.description),
                    )
                )
                return salvaged
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
    max_tokens: int | None = None,
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
            model=get_agno_model(max_tokens=max_tokens),
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


#: Shortest salvaged description kept; a shorter prefix is a fragment, not an
#: accessible description.
SALVAGE_MIN_CHARS = 40

#: Recorded in the salvaged answer's warnings, so the evidence says the
#: description is a recovered prefix and not what the model meant to send.
SALVAGE_WARNING = "description recovered from an answer cut off before its end"


def _salvage_truncated_description(error: ValidationError) -> VisionOutput | None:
    """The description of an answer that every try left cut off.

    A degenerate answer loops until max_tokens cuts the JSON off, and a retry
    with the same image usually loops again. The loop is often in a later
    field: in 006.pdf, page 23 (a periodic table), the description was whole
    and ``mentioned_elements`` listed element names until the cut. The
    description is kept with its repetition collapsed, its confidence set to 0
    and a warning. Only a cut answer is salvaged: JSON that is malformed
    elsewhere (an invalid escape, a stray character) was not cut, and nothing
    says which part of it to trust. Only a ``description`` is salvaged: a cut
    formula is wrong LaTeX, not a shorter one.
    """
    raw = next(
        (
            item["input"]
            for item in error.errors()
            if item["type"] == "json_invalid"
            and str((item.get("ctx") or {}).get("error", "")).startswith("EOF while parsing")
            and isinstance(item.get("input"), str)
        ),
        None,
    )
    if raw is None or not re.search(r'"kind"\s*:\s*"description"', raw):
        return None
    start = re.search(r'"description"\s*:\s*"', raw)
    if start is None:
        return None
    try:
        text, closed = _json_string_prefix(raw[start.end():])
    except ValueError:
        return None
    text, _ = collapse(text, [], reps=5, max_n=12)
    if not closed:
        # Cut mid-sentence: keep the sentences that ended.
        end = max(text.rfind(mark) for mark in (". ", ".\n", "! ", "? "))
        text = text[: end + 1] if end > 0 else text
    text = text.strip()
    if len(text) < SALVAGE_MIN_CHARS:
        return None
    language = re.search(r'"language"\s*:\s*"([A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*)"', raw)
    return VisionOutput(
        kind="description",
        description=text,
        language=language.group(1) if language else "und",
        confidence=0.0,
        warnings=[SALVAGE_WARNING],
    )


def _json_string_prefix(rest: str) -> tuple[str, bool]:
    """Decode the JSON string that ``rest`` starts inside of, up to its end or the cut.

    Returns the text and whether the string was closed. An escape the cut left
    incomplete is dropped. Raises ``ValueError`` for an invalid escape. The
    first unescaped quote closes the string: one inside the description would
    have failed parsing there, not at the end, so the answer is not salvaged.
    """
    index = 0
    while index < len(rest):
        char = rest[index]
        if char == '"':
            return json.loads(f'"{rest[:index]}"', strict=False), True
        if char == "\\":
            width = 6 if rest[index + 1 : index + 2] == "u" else 2
            if index + width > len(rest):
                break
            index += width
            continue
        index += 1
    return json.loads(f'"{rest[:index]}"', strict=False), False


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
