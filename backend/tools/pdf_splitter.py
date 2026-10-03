import re
from pathlib import Path

import pymupdf

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
    page_paths = []
    try:
        document = pymupdf.open(file_path)
    except pymupdf.FileNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    with document as source:
        if not source.is_pdf:
            raise ValueError("Source document is not a PDF.")
        if source.needs_pass:
            raise ValueError("Cannot split a password-protected PDF without a password.")
        total_pages = min(len(source), max_pages)

        logger.info(
            t(LOG_PDF_PAGE_COUNT_LOGGED).format(
                total=len(source), limit=total_pages
            )
        )

        for i in range(total_pages):
            output_path = tmpdir / f"pagina_{i + 1:03d}.pdf"
            with pymupdf.open() as output:
                output.insert_pdf(source, from_page=i, to_page=i)
                source_page = source[i]
                links = source_page.get_links()
                # Remote coordinates are not exposed faithfully by get_links().
                remote_source = [link for link in links if link["kind"] == pymupdf.LINK_GOTOR]
                remote_output = [link for link in output[0].get_links() if link["kind"] == pymupdf.LINK_GOTOR]
                for original, copied in zip(remote_source, remote_output, strict=True):
                    destination = _link_destination(source, original["xref"])
                    output.xref_set_key(copied["xref"], "A/D", destination)
                # insert_pdf excludes links to pages outside the copied range.
                for link in links:
                    target = link.get("page", -1)
                    if link["kind"] != pymupdf.LINK_GOTO or target < 0 or target == i:
                        continue
                    included = target < total_pages
                    output[0].insert_link({
                        **link,
                        "kind": pymupdf.LINK_GOTOR,
                        "file": (
                            f"pagina_{target + 1:03d}.pdf"
                            if included else file_path.resolve().as_posix()
                        ),
                        "page": 0 if included else target,
                    })
                    copied_xref = output[0].annot_xrefs()[-1][0]
                    # Preserve PDF coordinates, including crop boxes and rotation.
                    rectangle = source.xref_get_key(link["xref"], "Rect")[1]
                    output.xref_set_key(copied_xref, "Rect", rectangle)
                    destination = _link_destination(source, link["xref"])
                    destination = re.sub(
                        r"^\[\s*\d+\s+\d+\s+R", f"[{0 if included else target}",
                        destination, count=1,
                    )
                    output.xref_set_key(copied_xref, "A/D", destination)
                output.save(output_path)
            page_paths.append(output_path)
            logger.debug(
                t(LOG_PDF_PAGE_SAVED).format(page=i + 1, name=output_path.name)
            )

    logger.info(t(LOG_PDF_PAGES_EXTRACTED).format(count=total_pages, tmpdir=tmpdir))
    return page_paths


def _link_destination(document: pymupdf.Document, xref: int) -> str:
    """Resolve a PDF destination before copying it into another document."""
    kind, value = document.xref_get_key(xref, "A/D")
    if kind == "null":
        kind, value = document.xref_get_key(xref, "Dest")
    if kind == "xref":
        value = document.xref_object(int(value.split()[0]), compressed=True)
    return value
