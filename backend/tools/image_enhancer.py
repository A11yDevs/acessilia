"""Image transforms for the OCR imaging policy."""

import io

from PIL import Image
from docstruct.imaging.policy import upscale_factor

from backend.i18n import t
from backend.log_messages import (
    LOG_IMAGE_ORIENTED,
    LOG_IMAGE_PREPROCESS_FAILED,
    LOG_IMAGE_UPSCALED,
)
from backend.tools.logger import logger


def upscale_for_ocr(image_bytes: bytes) -> bytes:
    """Upscale a small page before OCR, using the pure policy from ``docstruct``.

    Small pages gain a lot from Lanczos upscaling before OCR (the single largest
    gain of the Tele line in Dr.DocBench: 77.47 -> 79.63). The factor comes from
    ``docstruct.imaging.policy.upscale_factor``: 2x below 800 px, 1.5x for
    800-1200 px, 1x above.

    Args:
        image_bytes (bytes): Encoded (JPEG/PNG) bytes of the page image; no default (required).

    Returns:
        bytes: JPEG bytes of the upscaled image, or the original bytes when no upscale applies.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        factor = upscale_factor(w, h)
        if factor <= 1.0:
            return image_bytes
        new_w, new_h = int(w * factor), int(h * factor)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        logger.debug(
            t(LOG_IMAGE_UPSCALED).format(factor=factor, old_width=w, old_height=h)
        )
        return buf.getvalue()
    except Exception as e:
        logger.error(t(LOG_IMAGE_PREPROCESS_FAILED).format(error=e))
        return image_bytes


def rotate_for_orientation(image_bytes: bytes, angle: int) -> bytes:
    """Rotate a page by ``angle`` degrees to correct its orientation.

    The angle comes from ``docstruct.imaging.policy.decide_orientation`` (0/90/180/270,
    counter-clockwise). The OCR-based detection itself lives in the pipeline, not here.

    Args:
        image_bytes (bytes): Encoded (JPEG/PNG) bytes of the page image; no default (required).
        angle (int): Counter-clockwise rotation to apply; 0 returns the input unchanged.

    Returns:
        bytes: JPEG bytes of the rotated image, or the original bytes when no rotation applies.
    """
    if angle % 360 == 0:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img = img.rotate(angle % 360, expand=True, resample=Image.Resampling.BICUBIC)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        logger.debug(t(LOG_IMAGE_ORIENTED).format(angle=angle % 360))
        return buf.getvalue()
    except Exception as e:
        logger.error(t(LOG_IMAGE_PREPROCESS_FAILED).format(error=e))
        return image_bytes
