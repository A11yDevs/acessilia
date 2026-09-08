from pathlib import Path

from pypdf import PdfReader, PdfWriter

from backend.i18n import t
from backend.log_messages import (
    LOG_PDF_PAGE_COUNT_LOGGED,
    LOG_PDF_PAGE_SAVED,
    LOG_PDF_PAGES_EXTRACTED,
)
from backend.tools.logger import logger


def split_pdf(file_path: Path, tmpdir: Path, max_pages: int = 50) -> list[Path]:
    """Split a PDF into individual per-page PDF files, capping the number extracted.

    Args:
        file_path (Path): Path to the source PDF to split; no default (required).
        tmpdir (Path): Destination directory the per-page PDF files are written to; no default (required).
        max_pages (int): Maximum number of pages to extract even if the document is longer; defaults to 50.

    Returns:
        list[Path]: Paths of the per-page PDF files written, in page order.
    """
    reader = PdfReader(file_path)
    total_pages = min(len(reader.pages), max_pages)

    logger.info(
        t(LOG_PDF_PAGE_COUNT_LOGGED).format(
            total=len(reader.pages), limit=total_pages
        )
    )

    page_paths = []
    for i in range(total_pages):
        writer = PdfWriter()
        writer.add_page(reader.pages[i])
        output_path = tmpdir / f"pagina_{i + 1:03d}.pdf"
        with open(output_path, "wb") as f:
            writer.write(f)
        page_paths.append(output_path)
        logger.debug(
            t(LOG_PDF_PAGE_SAVED).format(page=i + 1, name=output_path.name)
        )

    logger.info(t(LOG_PDF_PAGES_EXTRACTED).format(count=total_pages, tmpdir=tmpdir))
    return page_paths
