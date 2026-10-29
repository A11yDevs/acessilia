"""VisionAgent — generation of accessible audio descriptions for images."""

import asyncio
import functools
import hashlib
import json
import re

from docstruct.fusion.repetition import collapse
from pydantic import ValidationError

from backend.config.settings import settings
from backend.i18n import active_locale, t
from backend.log_messages import (
    LOG_VISION_AGENT_DESCRIPTION_TRUNCATED,
    LOG_VISION_AGENT_RATE_LIMIT_RETRY,
    LOG_VISION_AGENT_TIMEOUT_RETRY,
    LOG_VISION_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_REGION_RECOVERED,
    LOG_VISION_AGENT_REGION_RETRY,
    LOG_VISION_AGENT_REGION_SALVAGED,
    LOG_VISION_AGENT_SENDING_REGION,
    MSG_VISION_TRUNCATION_NOTICE,
)
from backend.tools.region_classifier import region_prompt_key
from backend.tools.logger import logger

from backend.tools.prompt_tools import (
    build_page_prompt,
    load_chemistry_prompt,
    load_region_prompt,
    load_system_prompt,
)
from backend.ai.models.ai_client import active_model_name, get_agno_model
from backend.services.cache import get_cached_bytes, options_cache_key, set_cache_bytes
from backend.agents.output_schemas import (
    PAGE_INSPECTION_INSTRUCTION,
    VISION_SCHEMA_INSTRUCTION,
    OutputModel,
    PageInspectionOutput,
    RunIncompleteError,
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
#: Only an answer that fails schema validation consumes one of the tries; a
#: rate-limit rejection gets its own backed-off budget instead, since it says
#: the provider is busy, not that the image is hard. Timeouts and other
#: provider failures fail at once, since repeating them without backoff
#: doubles the load. The provider SDK's own retries are turned off for that
#: reason: its default of 2 would silently rerun a 600s timeout twice with the
#: whole image again.
#:
#: This retry is deliberately kept instead of tuning temperature or repetition
#: penalties: changing those affects every answer and needs measuring first,
#: which the recovery INFO log makes possible. With Ollama the seed is fixed
#: (``get_agno_model``), so the retry differs from the first try only by
#: RETRY_INSTRUCTION; that changes the prompt and therefore the sampled tokens,
#: but a loop that does not depend on the prompt will still fail twice.
REGION_ATTEMPTS = 2

#: Regions whose answer may be a description get the chemistry rules: a drawn
#: molecule is described, not transcribed as a formula (006.pdf slides 25-26).
#: A formula region is left out: its answer is only kept when it is a formula,
#: and the data agent reads the same prompt with a schema that has no
#: description.
_CHEMISTRY_CLASSIFICATIONS = frozenset(
    {"embedded_image", "full_page_image", "full_page_fallback"}
)

#: Appended to the prompt of a retry. Each try is a fresh Agent with no
#: history, so it is phrased as a plain instruction, not as feedback on an
#: answer the model never saw; and it asks for no padding rather than for
#: brevity, since a long formula must still be transcribed whole.
RETRY_INSTRUCTION = (
    "Responda com um objeto JSON completo e válido, fechando todas as strings e "
    "chaves. Não repita tokens nem preencha campos com repetições ou espaços."
)

#: Seconds added to the client's HTTP timeout for the hard deadline around one
#: model call. That timeout bounds the HTTP exchange, but httpx applies it per
#: read: a provider (or a proxy in front of it) that trickles bytes keeps
#: resetting it, and the call outlives the configured bound. This deadline is
#: what the job actually waits for, so a hung call degrades the region instead
#: of stalling the pipeline. It sits above the HTTP timeout so an ordinary one
#: still arrives as the provider's own error.
#:
#: An abandoned call is not killed (Python cannot kill a thread): until the
#: provider resolves it keeps its worker thread, its open connection and its
#: per-call client, on the default executor shared with ``run_blocking`` and
#: the DataAgent. Isolating model calls on their own executor is tracked in
#: issue #276.
CALL_DEADLINE_GRACE_SECONDS = 30


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
        errors: list[str] | None = None,
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
            errors (list[str] | None): When given, receives a one-line summary of the error that made the call return None, for a caller that records why (default None).

        Returns:
            A validated visual result, or None when inference or validation fails. A
            description longer than the region token budget is truncated with a
            recorded warning; regions on the general budget (``full_budget``) are
            never truncated, because a cut there would lose document content.
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

        if not custom_prompt and classification in _CHEMISTRY_CLASSIFICATIONS:
            prompt = f"{prompt}\n{load_chemistry_prompt()}"
        prompt = f"{prompt}\n\n{VISION_SCHEMA_INSTRUCTION}"
        # A whole page, or a region inspected for review-structure (scanned text,
        # a table), may need the general budget to be transcribed; a picture
        # gets the smaller one, which also bounds what a degenerate try costs.
        max_tokens = (
            None
            if full_budget or classification.startswith("full_page")
            else settings.vision_region_max_tokens
        )

        cache_extra = _region_cache_extra(prompt, effective_mode, max_tokens)
        if settings.vision_region_cache_enabled:
            cached = await get_cached_bytes(
                image_bytes, extra=cache_extra, ttl=VISION_CACHE_TTL_SECONDS
            )
            if cached is not None:
                try:
                    return VisionOutput.model_validate(cached)
                except ValidationError:
                    pass  # stale or incompatible stored payload: describe again

        try:
            output = await _run_with_retry(
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
                if max_tokens is not None:
                    salvaged, _ = _truncate_description(
                        salvaged,
                        page_num=page_num,
                        region_type=classification,
                        limit_tokens=max_tokens,
                    )
                logger.warning(
                    t(LOG_VISION_AGENT_REGION_SALVAGED).format(
                        page_num=page_num,
                        type=classification,
                        chars=len(salvaged.description),
                    )
                )
                return salvaged
            if errors is not None:
                errors.append(_failure_summary(error))
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
        truncated = False
        if max_tokens is not None:
            output, truncated = _truncate_description(
                output,
                page_num=page_num,
                region_type=classification,
                limit_tokens=max_tokens,
            )
        if settings.vision_region_cache_enabled and _cacheable(output, truncated):
            await set_cache_bytes(
                image_bytes, output.model_dump(mode="json"), extra=cache_extra
            )
        return output

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
    """Ask the vision model for ``schema``, retrying answers that fail validation.

    A region gets ``REGION_ATTEMPTS`` tries; a rate-limit rejection does not
    consume one of them — it says the provider is busy, nothing about the
    answer — and gets its own smaller budget of backed-off retries instead. A
    call that runs out of time gets ``_TIMEOUT_RETRIES`` more, on the same
    grounds: a stalled provider says nothing about the image. Any other error
    (provider failure, incomplete run) fails at once.
    Each call also has a hard wall-clock deadline, because the client's HTTP
    timeout is applied per read and a provider that trickles bytes can outlive
    it.
    """
    attempt = 0
    rate_limit_retries = 0
    timeout_retries = 0
    while attempt < REGION_ATTEMPTS:
        attempt += 1
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
            model=get_agno_model(max_tokens=max_tokens, max_retries=0),
            output_schema=schema,
            telemetry=False,
        )
        run = functools.partial(
            agent.run, input=attempt_prompt, images=[Image(content=image_bytes)]
        )
        deadline = settings.model_call_timeout_seconds + CALL_DEADLINE_GRACE_SECONDS
        call = asyncio.ensure_future(asyncio.to_thread(run))
        try:
            response = await asyncio.wait_for(call, timeout=deadline)
        except TimeoutError as error:
            # ``wait_for`` cancels the awaited task on expiry; a provider's own
            # TimeoutError leaves it finished, so only that case is ours.
            timeout = (
                TimeoutError(f"no answer within the {deadline}s call deadline")
                if call.cancelled()
                else error
            )
            if timeout_retries < _TIMEOUT_RETRIES:
                timeout_retries += 1
                attempt -= 1  # a stalled provider says nothing about the answer
                logger.warning(
                    t(LOG_VISION_AGENT_TIMEOUT_RETRY).format(
                        page_num=page_num,
                        type=label,
                        retry=timeout_retries,
                        retries=_TIMEOUT_RETRIES,
                        error=timeout,
                    )
                )
                continue
            if timeout is error:
                raise
            raise timeout from error
        except Exception as error:
            if _is_rate_limited(error) and rate_limit_retries < _RATE_LIMIT_RETRIES:
                rate_limit_retries += 1
                attempt -= 1  # a rate limit says nothing about the answer
                await _wait_out_rate_limit(page_num, label, error, rate_limit_retries)
                continue
            raise
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
        except RunIncompleteError as error:
            if _is_rate_limited(error) and rate_limit_retries < _RATE_LIMIT_RETRIES:
                rate_limit_retries += 1
                attempt -= 1  # a rate limit says nothing about the answer
                await _wait_out_rate_limit(page_num, label, error, rate_limit_retries)
                continue
            raise
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


#: Pattern identifying a provider rate-limit rejection (HTTP 429) in the error
#: text an incomplete run carries — the provider's own error message, not
#: model content, which never reaches this check.
_RATE_LIMIT_PATTERN = re.compile(r"\b429\b|rate[ _-]?limit", re.IGNORECASE)

#: Extra tries granted to rate-limit rejections, on top of ``REGION_ATTEMPTS``:
#: a 429 says the provider is busy, nothing about the image, so it should not
#: consume one of the answer tries. The wait grows with each rejection and the
#: budget bounds it, so a saturated provider cannot stall the job forever.
_RATE_LIMIT_RETRIES = 2

#: Seconds before the first retry that follows a rate-limit rejection.
_RATE_LIMIT_RETRY_SECONDS = 20

#: Extra tries granted to a call that runs out of time, on top of
#: ``REGION_ATTEMPTS``. Kept at one: each try may wait the whole call deadline,
#: so a provider that stays stalled costs a picture two deadlines, not more.
_TIMEOUT_RETRIES = 1


def _is_rate_limited(error: BaseException) -> bool:
    """Whether a provider failure looks like an HTTP 429 rate-limit rejection.

    Typed signals first — an SDK exception carrying the HTTP status — and the
    error text as a fallback, scoped to incomplete runs: their content is the
    provider's error message, where a 429 shows up, while completed model
    content never takes this path.
    """
    if getattr(error, "status_code", None) == 429:
        return True
    if getattr(getattr(error, "response", None), "status_code", None) == 429:
        return True
    return isinstance(error, RunIncompleteError) and bool(
        _RATE_LIMIT_PATTERN.search(str(error))
    )


def _rate_limit_delay_seconds(error: BaseException, retry: int) -> int:
    """Seconds to wait after a rate-limit rejection.

    The provider's ``Retry-After`` wins when the SDK exposes it; otherwise the
    wait grows linearly with the retry count.
    """
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        return max(1, int(retry_after))
    except (TypeError, ValueError):
        return _RATE_LIMIT_RETRY_SECONDS * retry


async def _wait_out_rate_limit(
    page_num: int, label: str, error: BaseException, retry: int
) -> None:
    """Log a rate-limit rejection and wait before the next try.

    Unlike an unusable answer, a rate limit says nothing about the image, so
    the retry is not a new sample of the same question but a queued one; the
    wait keeps the extra load off the provider instead of doubling it.
    """
    delay = _rate_limit_delay_seconds(error, retry)
    logger.warning(
        t(LOG_VISION_AGENT_RATE_LIMIT_RETRY).format(
            page_num=page_num,
            type=label,
            retry=retry,
            retries=_RATE_LIMIT_RETRIES,
            delay=delay,
        )
    )
    await asyncio.sleep(delay)


#: Rough characters-per-token ratio for bounding a description's length. No
#: tokenizer is loaded for this check, so the cap is an approximation: its
#: point is bounding a runaway answer (some providers do not honor max_tokens
#: strictly), not metering exact tokens.
DESCRIPTION_CHARS_PER_TOKEN = 4

#: Recorded in the truncated answer's warnings, so the evidence says the
#: description is a capped prefix and not what the model meant to send.
DESCRIPTION_TRUNCATION_WARNING = (
    "description truncated to the {limit}-token budget ({chars} characters kept)"
)


def _truncate_description(
    output: VisionOutput, *, page_num: int, region_type: str, limit_tokens: int
) -> tuple[VisionOutput, bool]:
    """Cap a description at the given token budget; True when it cut.

    ``max_tokens`` normally already bounds the answer, but some providers do
    not honor it strictly, and a runaway description would otherwise reach the
    exports and the audio verbatim. The cap is applied to the final text, in
    characters estimated from the token budget the call site passed
    (``limit_tokens``); regions on the general budget (``full_budget``) are
    excluded by the caller, because a cut there would lose document content.

    The estimate is deliberately rough: ``DESCRIPTION_CHARS_PER_TOKEN``
    overestimates characters per token for Portuguese, so a capped text may
    still exceed the token budget it approximates. The point is bounding a
    runaway answer, not metering exact tokens.

    The truncated text ends with a reader-facing notice stating that the image
    is informationally very extensive and many details were not described, so
    nobody mistakes the bounded text for a complete description. The notice
    counts against the character cap, so the total stays within it.
    """
    limit_chars = limit_tokens * DESCRIPTION_CHARS_PER_TOKEN
    if len(output.description) <= limit_chars:
        return output, False
    notice = t(MSG_VISION_TRUNCATION_NOTICE)
    body_limit = max(0, limit_chars - len(notice) - 2)
    output.description = output.description[:body_limit].rstrip() + "\n\n" + notice
    output.warnings.append(
        DESCRIPTION_TRUNCATION_WARNING.format(
            limit=limit_tokens, chars=len(output.description)
        )
    )
    logger.warning(
        t(LOG_VISION_AGENT_DESCRIPTION_TRUNCATED).format(
            page_num=page_num,
            type=region_type,
            limit=limit_tokens,
            chars=len(output.description),
        )
    )
    return output, True


def _cacheable(output: VisionOutput, truncated: bool) -> bool:
    """Whether a validated answer is worth storing for reruns.

    A truncated description is a degraded answer — caching it would serve the
    same cut text for the TTL instead of trying for something better, the same
    reason a salvaged answer is never stored. Validation already rejects an
    empty description, so anything that reaches here and survives these two
    checks carries real content.
    """
    if truncated:
        return False
    return bool((output.description or output.formula_latex or "").strip())


#: TTL of a stored region description. Answers are sampled, not deterministic,
#: but a description is content, not state: re-describing the same image after
#: a restart or a retry adds cost without new information.
VISION_CACHE_TTL_SECONDS = 7 * 24 * 3600


def _region_cache_extra(prompt: str, mode: str, max_tokens: int | None) -> str:
    """Cache variant covering everything the answer depends on besides the image.

    The final prompt (system prompt, region instructions, schema instruction,
    any page numbers baked into a page prompt) plus the client, the model, the
    budget and the active locale fully determine what is asked and how the
    stored text reads; the version marks the truncation/salvage behavior, so a
    change there starts fresh entries instead of serving answers stored under
    the old rules. Calls that agree on all of these may share an answer.

    With ``AI_CLIENT=toolbox`` the model is the Toolbox provider id, not the
    weights it serves: the Toolbox names those in the provider's ``version``,
    which this key cannot see. When the weights behind the same provider id
    change, bump ``version`` here too (docs/adr/0012).
    """
    return options_cache_key(
        "vision_region",
        version="v1",
        ai_client=settings.ai_client,
        model=active_model_name(),
        mode=mode,
        budget=max_tokens,
        locale=active_locale(),
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


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


def _failure_summary(error: BaseException, limit: int = 300) -> str:
    """One line naming a failed call's error, short enough for element metadata."""
    if isinstance(error, ValidationError):
        return f"{type(error).__name__}: {_short_error(error, limit)}"
    text = " ".join(f"{type(error).__name__}: {error}".split())
    return text if len(text) <= limit else f"{text[:limit]}…"


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
