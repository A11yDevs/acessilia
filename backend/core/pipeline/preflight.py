"""What the pipeline checks before it extracts and plans: the media and the page limit.

``_inspect_media`` runs ``media.inspect`` and degrades visibly when it fails;
``_is_presentation`` reads the slide-deck decision from it. The page limit
(``MAX_PAGES``) is checked twice: early, on a PDF page count the remote parser
verified, and authoritatively on the manifest after extraction. Both raise
``DocumentTooLargeError``, a job-level failure. Moved verbatim from the PDDL
orchestrator (#402, phase 3, step 6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.i18n import t
from backend.log_messages import (
    LOG_MEDIA_INSPECT_FAILED,
)
from backend.stage_messages import (
    STAGE_DOCUMENT_TOO_MANY_PAGES,
)
from backend.tools.logger import logger
from backend.tools.media_inspect import inspect_source_media


class DocumentTooLargeError(ValueError):
    """The document has more pages than ``MAX_PAGES`` (job-level failure)."""


def _check_page_count(page_count: int) -> None:
    """Reject an oversized document as a whole with a user-facing message.

    A verified PDF count may be checked before costly extraction. The
    authoritative manifest count is checked afterwards for every format,
    including those without a reliable preflight count. Neither check allows
    partial processing beyond MAX_PAGES.

    Raises:
        DocumentTooLargeError: When the page count exceeds MAX_PAGES.
    """
    from backend.config.settings import settings

    if page_count > settings.max_pages:
        raise DocumentTooLargeError(
            t(STAGE_DOCUMENT_TOO_MANY_PAGES).format(
                page_count=page_count, max_pages=settings.max_pages
            )
        )


def _check_page_limit_before_extraction(inspection: dict[str, Any] | None) -> None:
    """Reject only PDF counts verified by the existing remote PDF parser.

    Scanned content streams, unknown counts and non-PDF formats are not a
    reliable early limit. They retain the authoritative post-extraction check.
    No local operational parser is introduced (ADR-0003).
    """
    if not isinstance(inspection, dict):
        return
    count = inspection.get("page_count")
    if (
        inspection.get("is_pdf") is True
        and inspection.get("page_count_source") == "pymupdf"
        and type(count) is int
        and count > 0
    ):
        _check_page_count(count)


def _check_page_limit(manifest: ProcessingManifest) -> None:
    """Authoritative limit after extraction, including formats without preflight."""
    _check_page_count(len(manifest.pages))


async def _inspect_media(
    source_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Runs ``media.inspect`` and degrades visibly when it fails.

    The inspection feeds the standalone-image heuristic and the presentation
    decision, and neither is required, so no failure of the step fails the
    job: any ``Exception`` (a ``ToolboxError``, but also an SDK bug or a client
    configuration error) makes the run continue without the signal, logs a
    warning and records the cause. Cancellation is not caught, since
    ``asyncio.CancelledError`` derives from ``BaseException``.

    Returns the inspection and the outcome for
    ``manifest.extractor.configuration``, since it runs before the manifest
    exists: ``media_inspection`` is ``toolbox``, ``disabled`` (by
    ``TOOLBOX_MEDIA_INSPECT_ENABLED``), ``source_missing`` or ``failed``, plus
    ``media_inspection_error`` on failure, and ``document_genre`` with its
    ``genre_signals`` when the Toolbox reports them.
    """
    from backend.config.settings import settings

    try:
        media_inspection = await inspect_source_media(source_path)
    except Exception as exc:  # noqa: BLE001 - the step degrades, never fails the job
        cause = f"{type(exc).__name__}: {exc}"
        logger.warning(
            t(LOG_MEDIA_INSPECT_FAILED).format(
                filename=source_path.name, error=cause
            )
        )
        return None, {"media_inspection": "failed", "media_inspection_error": cause}
    if media_inspection is not None:
        status = "toolbox"
    elif not settings.toolbox_media_inspect_enabled:
        status = "disabled"
    else:
        status = "source_missing"
    configuration: dict[str, Any] = {"media_inspection": status}
    if isinstance(media_inspection, dict) and media_inspection.get("document_genre"):
        configuration["document_genre"] = media_inspection["document_genre"]
        configuration["genre_signals"] = list(media_inspection.get("genre_signals") or [])
    return media_inspection, configuration


def _is_presentation(media_inspection: dict[str, Any] | None) -> bool:
    """Whether ``media.inspect`` reported a slide deck.

    A Toolbox older than pure-media-inspect 1.1.0 reports no genre, and a
    failed inspection reports nothing: both are treated as a document.
    """
    return (
        isinstance(media_inspection, dict)
        and media_inspection.get("document_genre") == "presentation"
    )
