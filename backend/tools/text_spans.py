"""The PDF text layer with fonts and geometry, through the Toolbox ``document.text.spans``.

Read only on the Toolbox (docs/adr/0003); the core uses it to find inline
math (docs/adr/0011). Pages are requested in batches the capability accepts,
and only the pages the caller names.
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
    from acessilia_sdk.toolbox.clients.pdf import TEXT_SPANS_MAX_PAGES

    from backend.config.settings import settings
    from backend.tools.toolbox_client import make_toolbox_client

    owned_client = client is None
    spans_client = client or make_toolbox_client(
        ToolboxPdfClient, resend_file_on_missing_artifact=artifact_id is not None
    )
    wanted = sorted(set(pages))
    by_page: dict[int, dict[str, Any]] = {}
    try:
        for offset in range(0, len(wanted), TEXT_SPANS_MAX_PAGES):
            document = await spans_client.text_spans(
                file_path=source_path,
                artifact_id=artifact_id,
                pages=wanted[offset : offset + TEXT_SPANS_MAX_PAGES],
                use_remote_cache=settings.toolbox_use_remote_cache,
            )
            for page in document["pages"]:
                by_page[int(page["page_number"])] = page
    finally:
        if owned_client:
            await spans_client.close()
    return by_page
