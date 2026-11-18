"""The page judge: which provider's reading of a page the vision model prefers.

For ``FUSION_MODE=dual``, ``_judge_texts`` picks the pages worth judging and
their two candidates; ``_judge_one_page`` renders the page (``_render_page_png``)
and asks ``document.adjudicate.page`` (``_judge_page``) through the SDK's page
judge operation (``acessilia_sdk.operations.page_judge``, #470 phase 4), with
the run's ``ToolboxConfig``. The operation renders and reads the answer; the
core keeps its decisions: the source check, which pages, the truncation
warning, the threshold that turns ``pB`` into a choice and what each failure
means. ``_judgement_result`` records each page's judgement on its elements and
reports the method's outcome.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from acessilia_core.config import ToolboxConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from acessilia_core.pipeline.handlers import messages as step_messages
from acessilia_core.pipeline.secondary import (
    _CALIBRATED_PAIR,
    _SecondaryExtraction,
    _page_markdown,
)
from acessilia_core.pipeline.toolbox import (
    _check_renderable,
    _render_client,
    _source_artifact_id,
)
from acessilia_core.i18n import t
from acessilia_core.logger import logger

if TYPE_CHECKING:
    from acessilia_sdk.operations.page_judge import PageJudgement


def _render_page_png(
    source_path: Path,
    page_number: int,
    artifact_id: str | None = None,
    media_type: str | None = None,
    *,
    toolbox: ToolboxConfig,
) -> bytes:
    """Page ``page_number`` (1-based) of a PDF, PNG or JPEG as PNG, rendered by the Toolbox.

    The SDK's ``render_judge_page`` (``JUDGE_PAGE_DPI``, longest side bounded
    by ``JUDGE_PAGE_MAX_SIDE``) with the run's ``toolbox``. The source is checked
    first, as for every render (``ValueError``), and the client resends a
    source the Toolbox lost.
    """
    from acessilia_sdk.operations.page_judge import render_judge_page
    from acessilia_sdk.runtime import run_sync

    _check_renderable(source_path, media_type)

    async def render() -> bytes:
        client = _render_client(artifact_id, toolbox)
        try:
            page = await render_judge_page(
                client, source_path, page_number=page_number, artifact_id=artifact_id
            )
        finally:
            await client.close()
        return page.image

    return run_sync(render())


def _judge_page(
    image: bytes, candidate_a: str, candidate_b: str, *, toolbox: ToolboxConfig
) -> PageJudgement:
    """The SDK's ``judge_page`` with the run's ``toolbox`` (sync wrapper)."""
    from acessilia_sdk.operations.page_judge import judge_page
    from acessilia_sdk.runtime import run_sync
    from acessilia_sdk.toolbox.clients import ToolboxAdjudicateClient

    from acessilia_core.toolbox.toolbox_client import make_toolbox_client

    async def call() -> PageJudgement:
        client = make_toolbox_client(ToolboxAdjudicateClient, toolbox)
        try:
            judgement = await judge_page(client, image, candidate_a, candidate_b)
        finally:
            await client.close()
        logger.info(
            "Toolbox: page adjudication finished (pB={})",
            judgement.document.get("pB", "?"),
        )
        return judgement

    return run_sync(call())


#: Characters per candidate the Toolbox's judge reads (``judge_max_chars`` of
#: ``qwen3-vl-8b`` in its ``providers-config.yaml``); beyond it the candidate is
#: cut on the Toolbox side, so the verdict does not cover the whole page.
_JUDGE_MAX_CHARS = 6000


def _judge_texts(
    manifest: ProcessingManifest, secondary: _SecondaryExtraction, page_number: int
) -> tuple[str, str, str, str] | None:
    """``(content, other, candidate A, candidate B)`` of a page, or ``None`` to skip it.

    Candidate A is the page the manifest carries and B the other provider's.
    A page the router took from the secondary provider is skipped when the
    artifact does not keep the primary page it replaced, and any page is
    skipped when either transcription is empty.
    """
    primary_name = _CALIBRATED_PAIR[0]
    page_elements = [
        element
        for element in sorted(manifest.elements, key=lambda e: e.reading_order)
        if element.page_number == page_number
    ]
    adopted = any(
        element.metadata.get("provider") == secondary.provider
        for element in page_elements
    )
    if adopted:
        if page_number not in secondary.replaced_primary:
            logger.warning(
                "vlm-pairwise-judge: page {} came from {}, but the artifact does not "
                "keep the {} page it replaced; skipped",
                page_number,
                secondary.provider,
                primary_name,
            )
            return None
        content, other = secondary.provider, primary_name
        other_blocks = secondary.replaced_primary[page_number]
    else:
        content, other = primary_name, secondary.provider
        other_blocks = secondary.pages.get(page_number, [])
    primary_md = _page_markdown(
        (element.type, element.text) for element in page_elements
    )
    secondary_md = _page_markdown(
        (str(block.get("type") or ""), block.get("text"))
        for block in other_blocks
    )
    if not primary_md.strip() or not secondary_md.strip():
        logger.info(
            "vlm-pairwise-judge: page {} has no two transcriptions; skipped",
            page_number,
        )
        return None
    return content, other, primary_md, secondary_md


def _judge_one_page(
    manifest: ProcessingManifest,
    page_number: int,
    content: str,
    other: str,
    primary_md: str,
    secondary_md: str,
    *,
    toolbox: ToolboxConfig,
) -> tuple[dict[str, Any] | None, MethodResult | None]:
    """Render a page, ask the judge, and read its answer: ``(judgement, failure)``.

    The judgement prefers ``other`` when ``pB > DEFAULT_NEW_THR``. A page
    that cannot be rendered, a refused or failed call, and an answer without a
    valid ``pB`` are failures of the method.
    """
    from docstruct.fusion.judge import DEFAULT_NEW_THR

    from acessilia_core.toolbox.toolbox_client import (
        ToolboxAuthenticationError,
        ToolboxContractViolation,
        ToolboxError,
    )

    source_path = Path(manifest.source.path)
    try:
        image = _render_page_png(
            source_path,
            page_number,
            _source_artifact_id(manifest),
            manifest.source.media_type,
            toolbox=toolbox,
        )
    except Exception as exc:  # noqa: BLE001 - rendering a broken source
        return None, MethodResult(
            success=False,
            validated=False,
            message=t(step_messages.MSG_JUDGE_RENDER_FAILED).format(
                page_number=page_number, error=exc),
        )
    truncated = max(len(primary_md), len(secondary_md)) > _JUDGE_MAX_CHARS
    if truncated:
        logger.warning(
            "vlm-pairwise-judge: page {} exceeds {} characters; "
            "the judge reads the truncated transcription",
            page_number,
            _JUDGE_MAX_CHARS,
        )
    logger.info("vlm-pairwise-judge: judging page {}", page_number)
    try:
        judgement = _judge_page(image, primary_md, secondary_md, toolbox=toolbox)
    except (ToolboxAuthenticationError, ToolboxContractViolation) as exc:
        return None, MethodResult(
            success=False,
            validated=False,
            message=t(step_messages.MSG_JUDGE_REFUSED).format(
                error_type=type(exc).__name__, error=exc),
        )
    except ToolboxError as exc:
        return None, MethodResult(
            success=False,
            validated=False,
            message=t(step_messages.MSG_JUDGE_UNAVAILABLE).format(
                error_type=type(exc).__name__, error=exc),
        )
    p_b = judgement.p_b
    if p_b is None:
        return None, MethodResult(
            success=False,
            validated=False,
            message=t(step_messages.MSG_JUDGE_INVALID_PB).format(
                page_number=page_number, p_b=repr(judgement.document.get("pB"))),
        )
    return {
        "content": content,
        "choice": other if p_b > DEFAULT_NEW_THR else content,
        "pB": p_b,
        "pB_ab": judgement.p_b_ab,
        "pA_ba": judgement.p_a_ba,
        "model": judgement.model,
        "truncated": truncated,
    }, None


def _judgement_result(
    elements: list[ManifestElement], judgements: dict[int, dict[str, Any]]
) -> MethodResult:
    """Record each page's judgement on its elements and report the method's outcome.

    A page whose judge prefers the other provider fails the method: the swap
    is recorded, not applied. Otherwise the pages are confirmed.
    """
    if not judgements:
        return MethodResult(success=False, validated=False, message=t(step_messages.MSG_JUDGE_NO_PAGES))
    for element in elements:
        if element.page_number in judgements:
            element.metadata["page_judgement"] = judgements[element.page_number]

    preferred = {
        page: judgement
        for page, judgement in judgements.items()
        if judgement["choice"] != judgement["content"]
    }
    if preferred:
        return MethodResult(
            success=False,
            validated=False,
            message=t(step_messages.MSG_JUDGE_PREFERS_OTHER).format(
                routes=", ".join(
                    f"p{page}: {j['choice']} pB={j['pB']:.2f}"
                    for page, j in sorted(preferred.items())
                )
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=t(step_messages.MSG_JUDGE_CONFIRMS).format(
            pages=", ".join(
                f"{page} ({j['content']}, pB={j['pB']:.2f})"
                if j["pB"] is not None
                else f"{page} ({j['content']}, {t(step_messages.MSG_JUDGE_AGREES)})"
                for page, j in sorted(judgements.items())
            )
        ),
    )
