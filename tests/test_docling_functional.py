from importlib.metadata import distributions
from importlib.util import find_spec
from pathlib import Path

import pytest

# The optional Docling stack is needed by the two extraction tests below; when absent from
# this environment (e.g. plain `poetry install` without the docling extra), those tests are
# skipped instead of failing, while containerized CI images where the stack exists continue to run them.
DOCSTACK_AVAILABLE = (
    find_spec("docling") is not None and find_spec("torch") is not None
)
skip_if_no_docstack = pytest.mark.skipif(
    not DOCSTACK_AVAILABLE,
    reason="Optional Docling stack (docling + CPU torch) unavailable in this environment",
)


FIXTURE = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"


@pytest.mark.docling
@skip_if_no_docstack
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
@skip_if_no_docstack
def test_docling_respects_enable_ocr_flag() -> None:
    """Checks that enable_ocr propagates to the structurer and pipeline options."""
    from backend.core.manifest.docling_extractor import DoclingManifestExtractor
    from backend.tools.structurer import DoclingStructurer

    # Builds structurers manually to inspect the flag
    structurer = DoclingStructurer(enable_ocr=False)
    assert structurer.enable_ocr is False

    structurer_with_ocr = DoclingStructurer(enable_ocr=True)
    assert structurer_with_ocr.enable_ocr is True

    # Checks the flag is propagated via _build_structurer
    extractor = DoclingManifestExtractor(enable_ocr=False)
    built = extractor._build_structurer()
    assert built.enable_ocr is False

    extractor_with_ocr = DoclingManifestExtractor(enable_ocr=True)
    built_with_ocr = extractor_with_ocr._build_structurer()
    assert built_with_ocr.enable_ocr is True


@pytest.mark.docling
def test_docling_removed_create_converter() -> None:
    """Checks that the dead-code `_create_converter` method is gone."""
    from backend.core.manifest.docling_extractor import DoclingManifestExtractor

    extractor = DoclingManifestExtractor(enable_ocr=True)
    assert not hasattr(extractor, "_create_converter")