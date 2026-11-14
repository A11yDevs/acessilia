"""The page judge: which provider's reading of a page the vision model prefers.

For ``FUSION_MODE=dual``, ``_judge_texts`` picks the pages worth judging and
their two candidates; ``_judge_one_page`` renders the page through the core's
binding to ``pdf.render`` (``_render_page_png``), asks ``document.adjudicate.page``
through the Toolbox (``_judge_page``) and reads the answer's ``pB`` with the
SDK's ``page_judgement_probability``; ``_judgement_result`` records each page's
judgement on its elements and reports the method's outcome. Moved verbatim from
the PDDL orchestrator once ADR-0017 was accepted (#402, phase 3, step 6).
Whether the render, adjudication and ``pB`` reading become an SDK operation, as
the formula chain did, is a later decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.clients.adjudicate import page_judgement_probability

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.core.pipeline.handlers import messages as step_messages
from backend.core.pipeline.secondary import (
    _CALIBRATED_PAIR,
    _SecondaryExtraction,
    _page_markdown,
)
from backend.core.pipeline.toolbox import (
    _source_artifact_id,
    _toolbox_render,
)
from backend.core.i18n import t
from backend.tools.logger import logger


#: Longest side of the page image sent to the judge. Two candidates plus the
#: image must fit one 8192-token slot of the production VLM server.
_JUDGE_PAGE_MAX_SIDE = 1600


def _render_page_png(
    source_path: Path,
    page_number: int,
    artifact_id: str | None = None,
    media_type: str | None = None,
) -> bytes:
    """Page ``page_number`` (1-based) of a PDF, PNG or JPEG as PNG, rendered by the Toolbox.

    At most 144 dpi, with the longest side bounded by ``_JUDGE_PAGE_MAX_SIDE``.
    """
    return _toolbox_render(
        source_path,
        page_number,
        media_type=media_type,
        dpi=144,
        max_side=_JUDGE_PAGE_MAX_SIDE,
        artifact_id=artifact_id,
    ).image


def _judge_page(image: bytes, candidate_a: str, candidate_b: str) -> dict[str, Any]:
    """Call document.adjudicate.page through the Toolbox (sync wrapper)."""
    import tempfile

    from acessilia_sdk.runtime import run_sync
    from acessilia_sdk.toolbox.clients import ToolboxAdjudicateClient

    from backend.tools.toolbox_client import make_toolbox_client

    async def call(path: Path) -> dict[str, Any]:
        client = make_toolbox_client(ToolboxAdjudicateClient)
        try:
            result = await client.judge_page(candidate_a, candidate_b, file_path=path)
        finally:
            await client.close()
        logger.info(
            "Toolbox: page adjudication finished (pB={})",
            result.get("document", {}).get("pB", "?"),
        )
        return result

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.png"
        path.write_bytes(image)
        return run_sync(call(path))


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
) -> tuple[dict[str, Any] | None, MethodResult | None]:
    """Render a page, ask the judge, and read its answer: ``(judgement, failure)``.

    The judgement prefers ``other`` when ``pB > DEFAULT_NEW_THR``. A page
    that cannot be rendered, a refused or failed call, and an answer without a
    valid ``pB`` are failures of the method.
    """
    from docstruct.fusion.judge import DEFAULT_NEW_THR

    from backend.tools.toolbox_client import (
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
        result = _judge_page(image, primary_md, secondary_md)
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
    document = result.get("document") or {}
    p_b = page_judgement_probability(document)
    if p_b is None:
        return None, MethodResult(
            success=False,
            validated=False,
            message=t(step_messages.MSG_JUDGE_INVALID_PB).format(
                page_number=page_number, p_b=repr(document.get("pB"))),
        )
    return {
        "content": content,
        "choice": other if p_b > DEFAULT_NEW_THR else content,
        "pB": p_b,
        "pB_ab": document.get("pB_ab"),
        "pA_ba": document.get("pA_ba"),
        "model": document.get("model"),
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
