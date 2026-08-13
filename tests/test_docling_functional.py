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