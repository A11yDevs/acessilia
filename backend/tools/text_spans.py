"""The PDF text layer with fonts and geometry, through the Toolbox ``document.text.spans``.

Read only on the Toolbox (docs/adr/0003); the core uses it to find inline
math (docs/adr/0011). ``ToolboxPdfClient.text_spans_by_page`` asks for only the
pages the caller names, in batches the capability accepts; this module binds
it to the core's settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def fetch_text_spans(
    source_path: Path,
    pages: list[int],
    *,
    artifact_id: str | None = None,
    client: Any | None = None,
) -> dict[int, dict[str, Any]]:
    """The ``text-spans@1`` page of each requested page number.

    Raises:
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot read
            the spans (the capability missing from its catalogue included).
    """
    from acessilia_sdk.toolbox.clients import ToolboxPdfClient

    from backend.config.settings import settings
    from backend.tools.toolbox_client import make_toolbox_client

    owned_client = client is None
    spans_client = client or make_toolbox_client(
        ToolboxPdfClient, resend_file_on_missing_artifact=artifact_id is not None
    )
    try:
        return await spans_client.text_spans_by_page(
            file_path=source_path,
            artifact_id=artifact_id,
            pages=pages,
            use_remote_cache=settings.toolbox_use_remote_cache,
        )
    finally:
        if owned_client:
            await spans_client.close()
