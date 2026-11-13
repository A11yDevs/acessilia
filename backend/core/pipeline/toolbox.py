"""The core's binding to the Toolbox render: the source artifact and ``pdf.render@2``.

``_source_artifact_id`` decides whether the extractor's stored source can be
referenced instead of uploaded; ``_toolbox_render`` binds the core's settings
to ``ToolboxPdfClient.render``, and ``_toolbox_formula_crop`` to the SDK's
``crop_formula_region`` (ADR-0017, #470 phase 3). The pipeline also accepts
TIFF, BMP, GIF and WebP, which ``pdf.render@2`` does not open
(``RENDER_MEDIA_TYPES``), and there is no local fallback (ADR-0003).

ADR-0017 keeps this binding in the core. Of the code built on it, the page
judge and the rest of the formula chain stay in the orchestrator until
ADR-0017 is accepted; the other callers moved with step 6 (#402, phase 3).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from acessilia_sdk.toolbox.clients.pdf import RENDER_MEDIA_TYPES

from backend.core.manifest.models import (
    ProcessingManifest,
)

if TYPE_CHECKING:
    from acessilia_sdk.operations.formula import FormulaCrop
    from acessilia_sdk.toolbox.clients.pdf import ClipOrigin, RenderedPage
    from docstruct.geometry.boxes import PageBox


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

    _check_renderable(source, media_type)

    async def render():
        client = _render_client(artifact_id)
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


def _check_renderable(source: Path, media_type: str | None) -> None:
    """Refuse, before any request, a source ``pdf.render@2`` would not open.

    The upload is labelled from the file extension; ``media_type`` (the
    manifest's) must agree with that label, and the label must be one of the
    SDK's ``RENDER_MEDIA_TYPES``. Raises ``ValueError`` saying which.
    """
    from acessilia_sdk.toolbox.transport import media_type_for

    sent_as = media_type_for(source)
    if media_type is not None and media_type != sent_as:
        raise ValueError(
            f"Source is {media_type} in the manifest but would be sent as {sent_as}"
        )
    if sent_as not in RENDER_MEDIA_TYPES:
        raise ValueError(
            f"pdf.render@2 renders PDF, PNG and JPEG inputs, not {sent_as}"
        )


def _render_client(artifact_id: str | None):
    """A ``ToolboxPdfClient`` from the core's settings.

    With ``artifact_id``, a source the Toolbox no longer stores is sent again.
    """
    from acessilia_sdk.toolbox.clients import ToolboxPdfClient

    from backend.tools.toolbox_client import make_toolbox_client

    return make_toolbox_client(
        ToolboxPdfClient, resend_file_on_missing_artifact=artifact_id is not None
    )


def _toolbox_formula_crop(
    source: Path,
    page_number: int,
    box: PageBox | None,
    *,
    media_type: str | None = None,
    artifact_id: str | None = None,
) -> FormulaCrop:
    """The SDK's ``crop_formula_region`` with the core's settings.

    A box that cannot be used is no crop, silently and for any source, as
    before the operation existed: it is checked before the source. The source
    is then checked as for ``_toolbox_render`` (``ValueError``), and the
    operation decides the crop (200 dpi, the box as the clip, a sliver is no
    crop) and raises the Toolbox's errors as they are. The client resends a
    source the Toolbox lost (``_render_client``). What to do with a failure is
    the caller's decision.
    """
    from acessilia_sdk.operations.formula import FormulaCrop, crop_formula_region
    from acessilia_sdk.runtime import run_sync
    from docstruct.geometry.boxes import best_effort_clip

    if best_effort_clip(box)[0] is None:
        return FormulaCrop(None, page_number, reason="no usable box")
    _check_renderable(source, media_type)

    async def crop() -> FormulaCrop:
        client = _render_client(artifact_id)
        try:
            return await crop_formula_region(
                client, source, page_number=page_number, box=box, artifact_id=artifact_id
            )
        finally:
            await client.close()

    return run_sync(crop())
