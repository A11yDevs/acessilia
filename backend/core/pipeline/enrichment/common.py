"""What the picture and table enrichment stages share.

``_extract_picture_bytes`` gives the image the vision model reads for an
element: its crop, rendered through the core's binding
(``backend.core.pipeline.toolbox``), or the image a DOCX or HTML picture
embeds. ``_retry_failed`` gives one more pass to the elements whose failure a
second try may fix. Moved verbatim from the PDDL orchestrator (#402, phase 3,
step 6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docstruct.data_uri import decode_data_uri
from docstruct.geometry.boxes import best_effort_clip

from backend.core.manifest.models import (
    ManifestElement,
)
from backend.core.pipeline.toolbox import (
    _toolbox_render,
)
from backend.i18n import n, t
from backend.log_messages import (
    LOG_PDDL_ELEMENT_CROP_FAILED,
    LOG_PDDL_VISION_RETRY_PASS_PICTURES,
    LOG_PDDL_VISION_RETRY_PASS_TABLES,
)
from backend.tools.logger import logger

if TYPE_CHECKING:
    from acessilia_sdk.toolbox.clients.pdf import ClipOrigin, RenderedPage

    from backend.agents.provider_breaker import ProviderBreaker


#: Picture failures a second try may fix: the provider gave no answer, or an
#: empty one (empty answers are never cached, so the try reaches the model). A
#: crop that could not be rendered will not render the second time either.
_RETRIED_VISION_FAILURES = frozenset({"model_failed", "empty_description"})


async def _retry_failed(
    failed: list[tuple[int, ManifestElement]],
    attempt: Callable[[int, ManifestElement], Coroutine[Any, Any, bool]],
    *,
    kind: str,
    breaker: ProviderBreaker,
) -> int:
    """Try once more, one at a time, what a vision stage left without a
    usable answer: the calls the model failed, and the pictures it answered
    empty.

    A provider that failed for a while (006.pdf v5 lost every picture after
    slide 10) may be back after a wait. The breaker lets the first try through
    even when open, and a failure of it opens the breaker again, so a provider
    that is still down costs one call, not one per object. Returns how many
    objects the pass enriched.
    """
    from backend.config.settings import settings

    if not failed:
        return 0
    delay = max(0, settings.vision_retry_pass_delay_seconds)
    kind_msgids = (
        LOG_PDDL_VISION_RETRY_PASS_PICTURES
        if kind == "pictures"
        else LOG_PDDL_VISION_RETRY_PASS_TABLES
    )
    logger.warning(
        n(*kind_msgids, len(failed)).format(count=len(failed), delay=delay)
    )
    await asyncio.sleep(delay)
    breaker.probe()
    enriched = 0
    for position, element in failed:
        enriched += await attempt(position, element)
    return enriched


#: Longest side of a picture crop sent to the vision model. The render runs at
#: 160 dpi and the Toolbox refuses more than 20 MP, so an unbounded crop of a
#: large standalone image (its page is sized in pixels) is rejected before the
#: model sees it. Bounding the side keeps every source renderable, and the
#: vision model's 8192-token slot would downscale it further anyway.
_PICTURE_MAX_SIDE = 2000


#: Largest image decoded from a picture's embedded ``src``. A DOCX or HTML
#: image is the author's file, not a bounded render, so an oversized one is
#: left undescribed instead of being held in memory and sent to the model.
_EMBEDDED_PICTURE_MAX_BYTES = 20 * 1024 * 1024


#: Embedded image types sent to the vision model as they are: the raster
#: formats the providers read (and that ``pdf.render`` also accepts as input).
#: A vector image (SVG) is not something the model can be shown.
_EMBEDDED_PICTURE_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg"})


def _extract_picture_bytes(
    source_file: Path,
    element: ManifestElement,
    fallback_page_number: int | None,
    artifact_id: str | None = None,
    media_type: str | None = None,
) -> tuple[bytes | None, int]:
    """The picture's box rendered by the Toolbox, or its whole page.

    A box the Toolbox refuses (outside the page) or a sliver of one is not a
    picture, so the page is described instead. Any other failure, the Toolbox
    being unavailable included, is not retried with the page: it is logged
    with its cause and the element is left without an image.

    A picture with no page (a DOCX or HTML source) has nothing to render; its
    image is the one the extraction embedded in it, if any, returned with
    page ``0``.
    """
    from acessilia_sdk.toolbox import (
        ToolboxCapabilityError,
        ToolboxIncompatibleEndpoint,
    )

    provenance = element.provenance[0] if element.provenance else None
    page_number = provenance.page_number if provenance is not None else (fallback_page_number or 0)
    if page_number < 1:
        image = decode_data_uri(
            element.metadata.get("src"),
            media_types=_EMBEDDED_PICTURE_TYPES,
            max_bytes=_EMBEDDED_PICTURE_MAX_BYTES,
        )
        return image, 0

    def render(clip=None, origin: ClipOrigin = "TOPLEFT") -> RenderedPage:
        return _toolbox_render(
            source_file, page_number, media_type=media_type, dpi=160,
            max_side=_PICTURE_MAX_SIDE, clip=clip,
            clip_origin=origin, artifact_id=artifact_id,
        )

    clip, origin = best_effort_clip(provenance.bbox if provenance is not None else None)
    try:
        if clip is None:
            return render().image, page_number
        try:
            page = render(clip, origin)
        except ToolboxIncompatibleEndpoint:
            raise
        except ToolboxCapabilityError:
            # The Toolbox refuses (HTTP 400) a box that does not intersect the page.
            return render().image, page_number
        left, top, right, bottom = page.clip
        if right - left < 4 or bottom - top < 4:
            return render().image, page_number
        return page.image, page_number
    except Exception:
        logger.exception(
            t(LOG_PDDL_ELEMENT_CROP_FAILED).format(element_id=element.id)
        )
        return None, page_number
