"""Media inspection of the source file through the Toolbox ``media.inspect``.

The inspection runs only on the Toolbox (docs/adr/0003): there is no local
fallback. With ``TOOLBOX_MEDIA_INSPECT_ENABLED=false`` the step is skipped,
and a Toolbox failure propagates so the caller decides how to degrade and
records the cause.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.i18n import t
from backend.log_messages import (
    LOG_MEDIA_INSPECT_SKIPPED_DISABLED,
    LOG_MEDIA_INSPECT_TOOLBOX_FINISHED,
)
from backend.tools.logger import logger


async def inspect_source_media(
    source_path: Path,
    *,
    client: Any | None = None,
    use_remote_cache: bool | None = None,
) -> dict[str, Any] | None:
    """Inspects the source file with the Toolbox ``media.inspect`` capability.

    Args:
        source_path (Path): File to inspect.
        client (ToolboxMediaInspectClient | None): Optional client to reuse; when None one is created and closed here.
        use_remote_cache (bool | None): Forwarded to the client; when None, TOOLBOX_USE_REMOTE_CACHE applies.

    Returns:
        dict | None: The ``artifact/media-inspection@1`` document, or None when the file does not exist or TOOLBOX_MEDIA_INSPECT_ENABLED is false.

    Raises:
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot inspect the file.
    """
    source_path = source_path.resolve()
    if not source_path.is_file():
        return None

    from backend.config.settings import settings

    if not settings.toolbox_media_inspect_enabled:
        logger.info(t(LOG_MEDIA_INSPECT_SKIPPED_DISABLED))
        return None

    from acessilia_sdk.toolbox.clients import ToolboxMediaInspectClient

    from backend.tools.toolbox_client import make_toolbox_client

    owned_client = client is None
    inspect_client = client or make_toolbox_client(ToolboxMediaInspectClient)
    try:
        result = await inspect_client.inspect(
            file_path=source_path,
            use_remote_cache=(
                use_remote_cache
                if use_remote_cache is not None
                else settings.toolbox_use_remote_cache
            ),
        )
    finally:
        if owned_client:
            await inspect_client.close()
    logger.info(
        t(LOG_MEDIA_INSPECT_TOOLBOX_FINISHED).format(
            nature=result.get("artifact_nature", "?"),
            visual=result.get("requires_visual_inspection", "?"),
        )
    )
    return result
