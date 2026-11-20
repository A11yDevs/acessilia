"""Reduce a vision payload through the Toolbox rendering capability."""

from __future__ import annotations

import tempfile
from pathlib import Path

from docstruct.imaging import image_dimensions

from acessilia_core.config import ToolboxConfig
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import LOG_VISION_CONTEXT_DOWNSCALE_FAILED
from acessilia_core.logger import logger
from acessilia_core.toolbox.toolbox_client import make_toolbox_client
from acessilia_sdk.toolbox import ToolboxError
from acessilia_sdk.toolbox.clients import ToolboxPdfClient


async def downscale_image(
    payload: bytes, scale: float = 0.5, *, toolbox: ToolboxConfig
) -> bytes | None:
    """``payload`` rendered by the Toolbox with its longest side times ``scale``.

    ``None`` when the image is not a PNG/JPEG whose size can be read, when it
    would not get smaller, or when the Toolbox cannot render it: the caller
    then lets the original context error stand.
    """
    size = image_dimensions(payload)
    if size is None:
        return None
    width, height, suffix = size
    max_side = max(1, int(max(width, height) * scale))
    if max_side >= max(width, height):
        return None
    client = None
    try:
        client = make_toolbox_client(ToolboxPdfClient, toolbox)
        with tempfile.TemporaryDirectory(prefix="vision-context-") as directory:
            source = Path(directory) / f"region{suffix}"
            source.write_bytes(payload)
            rendered = await client.render(file_path=source, max_side=max_side)
        return rendered.image
    except (ToolboxError, OSError, ValueError) as error:
        logger.warning(t(LOG_VISION_CONTEXT_DOWNSCALE_FAILED).format(error=error))
        return None
    finally:
        if client is not None:
            await client.close()
