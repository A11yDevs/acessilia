"""Classification of Docling formula regions."""

from backend.tools.region_classifier import (
    Region,
    classify_region,
    formula_already_extracted,
)


def _formula_region(text: str = "", enriched: bool = False) -> Region:
    return Region(
        bbox=(10.0, 10.0, 200.0, 60.0),
        type="formula",
        text=text,
        image_bytes=None,
        confidence=0.8,
        page_num=1,
        metadata={
            "source": "docling",
            "docling_type": "formula",
            "docling_label": "DocItemLabel.FORMULA",
            "docling_label_kind": "formula",
            "subtype": "",
            "formula_enriched": enriched,
        },
    )


def test_docling_formula_region_classified_as_formula():
    assert classify_region(_formula_region()) == "formula"


def test_formula_already_extracted_requires_enrichment_and_text():
    assert formula_already_extracted(_formula_region("E=mc^2", enriched=True))
    assert not formula_already_extracted(_formula_region("E=mc^2", enriched=False))
    assert not formula_already_extracted(_formula_region("", enriched=True))
    assert not formula_already_extracted(_formula_region("   ", enriched=True))
