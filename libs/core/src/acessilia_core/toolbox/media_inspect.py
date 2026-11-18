"""Media inspection of the source file through the Toolbox ``media.inspect``.

The inspection runs only on the Toolbox (docs/adr/0003): there is no local
fallback. With ``TOOLBOX_MEDIA_INSPECT_ENABLED=false`` the step is skipped,
and a Toolbox failure propagates so the caller decides how to degrade and
records the cause.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_MEDIA_INSPECT_SKIPPED_DISABLED,
    LOG_MEDIA_INSPECT_TOOLBOX_FINISHED,
)
from acessilia_core.config import ToolboxConfig
from acessilia_core.logger import logger


async def inspect_source_media(
    source_path: Path,
    *,
    toolbox: ToolboxConfig,
    client: Any | None = None,
) -> dict[str, Any] | None:
    """Inspects the source file with the Toolbox ``media.inspect`` capability.

    Args:
        source_path (Path): File to inspect.
        client (ToolboxMediaInspectClient | None): Optional client to reuse; when None one is created and closed here.
        toolbox (ToolboxConfig): The run's Toolbox configuration: whether the inspection runs, and whether the Toolbox cache is used.

    Returns:
        dict | None: The ``artifact/media-inspection@1`` document, or None when the file does not exist or ``toolbox.media_inspect_enabled`` is false.

    Raises:
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot inspect the file or returns no document.
    """
    source_path = source_path.resolve()
    if not source_path.is_file():
        return None

    if not toolbox.media_inspect_enabled:
        logger.info(t(LOG_MEDIA_INSPECT_SKIPPED_DISABLED))
        return None

    from acessilia_sdk.toolbox.clients import ToolboxMediaInspectClient
    from acessilia_sdk.toolbox.errors import ToolboxContractViolation

    from acessilia_core.toolbox.toolbox_client import make_toolbox_client

    owned_client = client is None
    inspect_client = client or make_toolbox_client(ToolboxMediaInspectClient, toolbox)
    try:
        result = await inspect_client.inspect(
            file_path=source_path,
            use_remote_cache=toolbox.use_remote_cache,
        )
    finally:
        if owned_client:
            await inspect_client.close()
    if not isinstance(result, dict):
        raise ToolboxContractViolation(
            "media.inspect returned no inspection document"
        )
    logger.info(
        t(LOG_MEDIA_INSPECT_TOOLBOX_FINISHED).format(
            nature=result.get("artifact_nature", "?"),
            visual=result.get("requires_visual_inspection", "?"),
        )
    )
    return result
