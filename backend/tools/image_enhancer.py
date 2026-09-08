import cv2
import numpy as np
from PIL import Image
import io
from backend.i18n import t
from backend.log_messages import (
    LOG_IMAGE_PREPROCESS_FAILED,
    LOG_IMAGE_RESIZED,
    LOG_IMAGE_ROTATED,
)
from backend.tools.logger import logger

VIT_MAX_DIMENSION = 1344


def resize_image(image_bytes: bytes) -> bytes:
    """Resize an image so its longest side fits the vision model's maximum dimension.

    Args:
        image_bytes (bytes): Encoded (JPEG/PNG) bytes of the image to resize; no default (required).

    Returns:
        bytes: JPEG bytes of the resized image, or the original bytes unchanged when the image already fits.
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size

    if w > VIT_MAX_DIMENSION or h > VIT_MAX_DIMENSION:
        ratio = VIT_MAX_DIMENSION / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        logger.debug(
            t(LOG_IMAGE_RESIZED).format(
                old_width=w, old_height=h, new_width=new_w, new_height=new_h
            )
        )
        return buf.getvalue()

    return image_bytes


def enhance_image_for_ocr(image_bytes: bytes) -> bytes:
    """Pre-process an image for OCR: denoise, auto-rotate to horizon, and equalize contrast.

    Args:
        image_bytes (bytes): Encoded (JPEG/PNG) image bytes to enhance; no default (required).

    Returns:
        bytes: Denoised, rotated, and contrast-equalized JPEG bytes; the original bytes unchanged when processing fails.
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return image_bytes

        img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        coords = np.column_stack(np.where(gray > 0))
        angle = cv2.minAreaRect(coords)[-1]

        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        if abs(angle) > 0.5:
            (h, w) = img.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            img = cv2.warpAffine(
                img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )
            logger.debug(
                t(LOG_IMAGE_ROTATED).format(angle=angle)
            )

        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        L, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(L)
        limg = cv2.merge((cl, a, b))
        img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        _, buffer = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        return buffer.tobytes()

    except Exception as e:
        logger.error(t(LOG_IMAGE_PREPROCESS_FAILED).format(error=e))
        return image_bytes


def is_math_likely(text: str) -> bool:
    """Heuristically decide whether a text chunk looks like a mathematical formula.

    Args:
        text (str): The extracted text chunk to inspect for formula indicators; no default (required).

    Returns:
        bool: True when more than two known mathematical indicators are present in the chunk.
    """
    math_indicators = [
        "=",
        "+",
        "-",
        "*",
        "/",
        "^",
        "√",
        "∫",
        "∑",
        "π",
        "θ",
        "²",
        "³",
        "log",
        "sin",
        "cos",
        "tan",
    ]
    count = sum(1 for indicator in math_indicators if indicator in text)
    return count > 2
