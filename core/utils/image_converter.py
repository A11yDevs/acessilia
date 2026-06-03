from pathlib import Path

import fitz

from core.utils.logger import logger


def convert_pdf_to_png(pdf_path: Path, dpi: int = 150) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
        logger.debug("Pagina convertida para PNG: {} bytes", len(png_bytes))
        return png_bytes
    finally:
        doc.close()
