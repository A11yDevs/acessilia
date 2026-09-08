"""Image processing and region-cropping utilities for the vision pipeline."""
import io

import fitz
from PIL import Image
from pathlib import Path

from backend.i18n import t
from backend.log_messages import LOG_REGION_CROP_FAILED
from backend.config.settings import settings
from backend.tools.image_converter import convert_pdf_to_png
from backend.tools.image_enhancer import enhance_image_for_ocr, resize_image
from backend.tools.region_extractor import Region
from backend.tools.structurer import BaseStructurer
from backend.tools.logger import logger

def compress_to_jpg(image_bytes: bytes, max_width: int | None = None, quality: int | None = None) -> bytes:
    max_width = max_width or settings.max_page_width
    quality = quality or settings.jpg_quality
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P": img = img.convert("RGBA")
        alpha = img.split()[-1] if "A" in img.mode else None
        background.paste(img, mask=alpha)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    width, height = img.size
    if width > max_width:
        ratio = max_width / width
        img = img.resize((max_width, int(height * ratio)), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()

def prepare_image_bytes(raw_bytes: bytes) -> bytes:
    return resize_image(enhance_image_for_ocr(compress_to_jpg(raw_bytes)))

def crop_region_image(structurer: BaseStructurer, page_path: Path, region: Region) -> bytes | None:
    """Crop a manifest region from a rendered page and return its enhanced image bytes.

    Args:
        structurer (BaseStructurer): Document structurer that knows how to crop a page region at 200 dpi.
        page_path (Path): Path to the single-page PDF being cropped.
        region (Region): Manifest region whose bbox selects the crop rectangle on the page.

    Returns:
        bytes | None: JPEG-compressed, OCR-enhanced region image bytes, or None when the crop raised (a critical log line is then emitted).
    """
    try:
        doc = fitz.open(page_path)
        try:
            page = doc[0]
            region_png = structurer.crop_region(page, region.bbox, dpi=200)
        finally:
            doc.close()
        return prepare_image_bytes(region_png)
    except Exception as error:
        logger.critical(t(LOG_REGION_CROP_FAILED).format(error=error))
        return None

def render_full_page(page_path: Path) -> bytes:
    return prepare_image_bytes(convert_pdf_to_png(page_path, settings.pdf_split_dpi))
