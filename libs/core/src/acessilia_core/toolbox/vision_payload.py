"""Reduce a vision payload through the SDK's downscale helper and the run's ToolboxConfig."""

from __future__ import annotations

import math

from acessilia_sdk.toolbox import ToolboxError
from acessilia_sdk.toolbox.clients import ToolboxPdfClient
from acessilia_sdk.toolbox.clients.pdf import downscale_image as _sdk_downscale_image
from docstruct.imaging import image_dimensions

from acessilia_core.config import ToolboxConfig
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import LOG_VISION_CONTEXT_DOWNSCALE_FAILED
from acessilia_core.logger import logger
from acessilia_core.toolbox.toolbox_client import make_toolbox_client


async def downscale_image(
    payload: bytes, scale: float = 0.5, *, toolbox: ToolboxConfig
) -> bytes | None:
    """``payload`` rendered by the Toolbox with its longest side times ``scale``.

    Delegates dimension parsing and ``pdf.render@2`` invocation to
    :func:`acessilia_sdk.toolbox.clients.pdf.downscale_image`, keeping
    ``ToolboxConfig`` client lifecycle, localized logging, and best-effort
    ``None`` recovery in the core.
    """
    if (
        isinstance(scale, bool)
        or not isinstance(scale, (int, float))
        or not math.isfinite(scale)
        or scale <= 0
    ):
        return None
    size = image_dimensions(payload)
    if size is None:
        return None
    width, height, _ = size
    if max(1, int(max(width, height) * scale)) >= max(width, height):
        return None
    client = None
    try:
        client = make_toolbox_client(ToolboxPdfClient, toolbox)
        return await _sdk_downscale_image(client, payload, scale)
    except (ToolboxError, OSError, ValueError) as error:
        logger.warning(t(LOG_VISION_CONTEXT_DOWNSCALE_FAILED).format(error=error))
        return None
    finally:
        if client is not None:
            await client.close()
