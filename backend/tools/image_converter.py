from pathlib import Path

import fitz

from backend.i18n import t
from backend.log_messages import LOG_PAGE_CONVERTED_TO_PNG
from backend.tools.logger import logger


def convert_pdf_to_png(pdf_path: Path, dpi: int = 150) -> bytes:
    """Rasterize the first page of a PDF into PNG image bytes.

    Args:
        pdf_path (Path): Path to the source PDF file to rasterize; no default (required).
        dpi (int): Rasterization resolution in dots per inch used by the pixmap renderer; defaults to 150.

    Returns:
        bytes: The PNG-encoded bytes of the converted first page.
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
        logger.debug(t(LOG_PAGE_CONVERTED_TO_PNG).format(size=len(png_bytes)))
        return png_bytes
    finally:
        doc.close()
