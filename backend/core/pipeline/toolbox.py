"""The core's binding to the Toolbox render: the source artifact and ``pdf.render@2``.

``_source_artifact_id`` decides whether the extractor's stored source can be
referenced instead of uploaded; ``_toolbox_render`` binds the core's settings
to ``ToolboxPdfClient.render``. The pipeline also accepts TIFF, BMP, GIF and
WebP, which ``pdf.render@2`` does not open (``RENDER_MEDIA_TYPES``), and there
is no local fallback (ADR-0003).

ADR-0017 keeps this binding in the core. The compositions built on it, the page
judge and the formula chain, stay in the orchestrator until ADR-0017 decides
their split. Moved verbatim from the PDDL orchestrator (#402, phase 3, step 6).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from acessilia_sdk.toolbox.clients.pdf import RENDER_MEDIA_TYPES

from backend.core.manifest.models import (
    ProcessingManifest,
)

if TYPE_CHECKING:
    from acessilia_sdk.toolbox.clients.pdf import ClipOrigin, RenderedPage


def _source_artifact_id(manifest: ProcessingManifest) -> str | None:
    """The Toolbox artifact of the source document, when the extractor stored one.

    Artifact ids are content addressed, so the id is used only when its digest
    is the manifest's source SHA-256: an id of any other document (a restored
    or reassembled manifest, a wrong id) would have the Toolbox render pixels
    the evidence does not describe. Otherwise the file itself is sent.
    """
    from acessilia_sdk.toolbox import ArtifactRef, ToolboxContractViolation

    value = (manifest.extractor.configuration or {}).get("artifact_id")
    if not isinstance(value, str) or not value:
        return None
    try:
        ref = ArtifactRef.parse(value)
    except ToolboxContractViolation:
        return None
    return value if ref.digest == manifest.source.sha256 else None


def _toolbox_render(
    source: Path,
    page_number: int,
    *,
    media_type: str | None = None,
    dpi: int,
    max_side: int | None = None,
    clip: tuple[float, float, float, float] | None = None,
    clip_origin: ClipOrigin = "TOPLEFT",
    artifact_id: str | None = None,
) -> RenderedPage:
    """Render a page (or a region of it) on the Toolbox with ``pdf.render@2``.

    There is no local rendering (docs/adr/0003): the Toolbox converts, clips,
    bounds and refuses oversized renders, and reports what it applied. With
    ``artifact_id`` the source already stored by the extractor is referenced
    instead of uploaded; the file is sent only if the Toolbox no longer has it.

    The upload is labelled from the file extension; ``media_type`` (the
    manifest's) must agree with that label. Inputs outside the SDK's
    ``RENDER_MEDIA_TYPES`` are refused here with a ``ValueError``, before
    any request, so the method fails with that reason and not a Toolbox error.
    """
    from acessilia_sdk.runtime import run_sync
    from acessilia_sdk.toolbox.clients import ToolboxPdfClient
    from acessilia_sdk.toolbox.transport import media_type_for

    from backend.tools.toolbox_client import make_toolbox_client

    sent_as = media_type_for(source)
    if media_type is not None and media_type != sent_as:
        raise ValueError(
            f"Source is {media_type} in the manifest but would be sent as {sent_as}"
        )
    if sent_as not in RENDER_MEDIA_TYPES:
        raise ValueError(
            f"pdf.render@2 renders PDF, PNG and JPEG inputs, not {sent_as}"
        )

    async def render():
        client = make_toolbox_client(
            ToolboxPdfClient, resend_file_on_missing_artifact=artifact_id is not None
        )
        try:
            return await client.render(
                file_path=source,
                artifact_id=artifact_id,
                page_number=page_number,
                dpi=dpi,
                max_side=max_side,
                clip=clip,
                clip_origin=clip_origin,
            )
        finally:
            await client.close()

    return run_sync(render())
