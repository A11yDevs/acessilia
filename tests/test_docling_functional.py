from importlib.metadata import distributions
from pathlib import Path

import pytest


FIXTURE = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"


@pytest.mark.docling
def test_docling_converts_real_pdf_with_cpu_only_torch() -> None:
    import torch

    from backend.core.manifest.docling_extractor import DoclingManifestExtractor

    installed_packages = {
        distribution.metadata["Name"].lower().replace("_", "-")
        for distribution in distributions()
        if distribution.metadata["Name"]
    }
    assert torch.version.cuda is None
    assert "triton" not in installed_packages
    assert not any(name.startswith("nvidia-") for name in installed_packages)

    extraction = DoclingManifestExtractor(enable_ocr=True).extract(FIXTURE)

    assert extraction.version != "unknown"
    assert extraction.duration_ms >= 0
    assert extraction.configuration == {
        "ocr": True,
        "table_structure": True,
        "remote_services": False,
    }
    assert extraction.document.export_to_markdown().strip()


@pytest.mark.docling
def test_docling_respects_enable_ocr_flag() -> None:
    """Verifica que enable_ocr é propagado para o structurer e pipeline_options."""
    from backend.core.manifest.docling_extractor import DoclingManifestExtractor
    from backend.tools.structurer import DoclingStructurer

    # Cria structurer manualmente para inspecionar o flag
    structurer = DoclingStructurer(enable_ocr=False)
    assert structurer.enable_ocr is False

    structurer_with_ocr = DoclingStructurer(enable_ocr=True)
    assert structurer_with_ocr.enable_ocr is True

    # Verifica que o flag é propagado via _build_structurer
    extractor = DoclingManifestExtractor(enable_ocr=False)
    built = extractor._build_structurer()
    assert built.enable_ocr is False

    extractor_with_ocr = DoclingManifestExtractor(enable_ocr=True)
    built_with_ocr = extractor_with_ocr._build_structurer()
    assert built_with_ocr.enable_ocr is True


@pytest.mark.docling
def test_docling_removed_create_converter() -> None:
    """Verifica que _create_converter foi removido (código morto)."""
    from backend.core.manifest.docling_extractor import DoclingManifestExtractor

    extractor = DoclingManifestExtractor(enable_ocr=True)
    assert not hasattr(extractor, "_create_converter")