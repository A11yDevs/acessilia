"""Reduce a vision payload through the Toolbox rendering capability."""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from acessilia_sdk.toolbox import ToolboxError
from acessilia_sdk.toolbox.clients import ToolboxPdfClient

from backend.i18n import t
from backend.log_messages import LOG_VISION_CONTEXT_DOWNSCALE_FAILED
from backend.tools.logger import logger
from backend.tools.toolbox_client import make_toolbox_client


def _image_size(payload: bytes) -> tuple[int, int, str] | None:
    """Read PNG/JPEG header dimensions without decoding or transforming pixels."""
    if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24 and payload[12:16] == b"IHDR":
        width, height = struct.unpack(">II", payload[16:24])
        return (width, height, ".png") if width and height else None
    if payload.startswith(b"\xff\xd8"):
        position = 2
        while position + 4 <= len(payload):
            if payload[position] != 0xFF:
                return None
            while position < len(payload) and payload[position] == 0xFF:
                position += 1
            if position >= len(payload):
                return None
            marker = payload[position]
            position += 1
            if marker in {0xD9, 0xDA}:
                return None
            length = int.from_bytes(payload[position:position + 2], "big")
            if length < 2 or position + length > len(payload):
                return None
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if length < 7:
                    return None
                height, width = struct.unpack(">HH", payload[position + 3:position + 7])
                return (width, height, ".jpg") if width and height else None
            position += length
    return None


async def downscale_image(payload: bytes, scale: float = 0.5) -> bytes | None:
    """``payload`` rendered by the Toolbox with its longest side times ``scale``.

    ``None`` when the image is not a PNG/JPEG whose size can be read, when it
    would not get smaller, or when the Toolbox cannot render it: the caller
    then lets the original context error stand.
    """
    size = _image_size(payload)
    if size is None:
        return None
    width, height, suffix = size
    max_side = max(1, int(max(width, height) * scale))
    if max_side >= max(width, height):
        return None
    client = None
    try:
        client = make_toolbox_client(ToolboxPdfClient)
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
