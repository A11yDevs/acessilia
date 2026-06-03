from pathlib import Path

from pypdf import PdfReader, PdfWriter

from core.utils.logger import logger


def split_pdf(file_path: Path, tmpdir: Path, max_pages: int = 50) -> list[Path]:
    reader = PdfReader(file_path)
    total_pages = min(len(reader.pages), max_pages)

    logger.info("PDF tem {} paginas, processando {}", len(reader.pages), total_pages)

    page_paths = []
    for i in range(total_pages):
        writer = PdfWriter()
        writer.add_page(reader.pages[i])
        output_path = tmpdir / f"pagina_{i + 1:03d}.pdf"
        with open(output_path, "wb") as f:
            writer.write(f)
        page_paths.append(output_path)
        logger.debug("Pagina {} salva: {}", i + 1, output_path.name)

    logger.info("{} paginas extraidas para {}", total_pages, tmpdir)
    return page_paths
