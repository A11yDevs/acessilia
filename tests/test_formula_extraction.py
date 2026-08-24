"""Testes do caminho de extração de fórmulas (Docling enrichment vs LLM)."""

from pathlib import Path

import pytest

from backend.agents.reader_agent import ReaderAgent
from backend.tools.region_classifier import (
    classify_region,
    formula_already_extracted,
)
from backend.tools.region_extractor import Region


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


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setattr(
        "backend.agents.reader_agent.get_structurer_instance", lambda: object()
    )
    monkeypatch.setattr(
        "backend.agents.reader_agent.crop_region_image",
        lambda structurer, page_path, region: b"fake-image-bytes",
    )
    return ReaderAgent()


def test_enriched_formula_goes_straight_to_editor(reader):
    region = _formula_region(r"E=mc^2", enriched=True)
    tasks = reader._extract_mixed_tasks(Path("page.pdf"), [region], 1, 1)

    assert len(tasks) == 1
    assert tasks[0].agent_target == "editor"
    assert tasks[0].classification == "formula"
    assert tasks[0].text == r"$E=mc^2$"  # delimitado p/ virar bloco math
    assert tasks[0].image_bytes is None


def test_non_enriched_formula_falls_back_to_data_agent(reader):
    region = _formula_region("", enriched=False)
    tasks = reader._extract_mixed_tasks(Path("page.pdf"), [region], 1, 1)

    assert len(tasks) == 1
    assert tasks[0].agent_target == "data"
    assert tasks[0].classification == "formula"
    assert tasks[0].image_bytes == b"fake-image-bytes"


def test_duplicate_enriched_formulas_are_deduplicated(reader):
    regions = [
        _formula_region(r"\frac{a}{b}", enriched=True),
        _formula_region(r"\frac{a}{b}", enriched=True),
    ]
    tasks = reader._extract_mixed_tasks(Path("page.pdf"), regions, 1, 1)

    formula_tasks = [t for t in tasks if t.classification == "formula"]
    assert len(formula_tasks) == 1


# ── Sentinela [FORMULA] do VisionAgent (imagem que na verdade é fórmula) ──


def _image_task() -> "RegionTask":
    from backend.agents.types import RegionTask

    region = Region(
        bbox=(10.0, 10.0, 200.0, 60.0),
        type="image",
        text="",
        image_bytes=b"fake",
        confidence=0.9,
        page_num=1,
        metadata={"source": "docling"},
    )
    return RegionTask(
        agent_target="vision",
        classification="embedded_image",
        text="",
        image_bytes=b"fake",
        region=region,
        page_num=1,
    )


def test_editor_unwraps_formula_sentinel_from_vision():
    from backend.agents.editor_agent import EditorAgent

    task = _image_task()
    result = EditorAgent().consolidate_page(
        [task], {0: r"[FORMULA] E=mc^2"}
    )

    assert result == r"$E=mc^2$"
    assert "Início de imagem" not in result


def test_editor_keeps_image_marker_for_normal_descriptions():
    from backend.agents.editor_agent import EditorAgent

    task = _image_task()
    result = EditorAgent().consolidate_page(
        [task], {0: "Fotografia de um gato sobre uma mesa."}
    )

    assert "Início de imagem" in result
    assert "Fotografia de um gato" in result


def test_editor_skips_empty_formula_sentinel():
    from backend.agents.editor_agent import EditorAgent

    task = _image_task()
    result = EditorAgent().consolidate_page([task], {0: "[FORMULA]"})

    assert result == ""


# ── Cascata local (OCR + CodeFormula) para imagens com fórmulas ──


def _image_region() -> Region:
    return Region(
        bbox=(10.0, 10.0, 300.0, 120.0),
        type="image",
        text="",
        image_bytes=b"fake",
        confidence=0.9,
        page_num=1,
        metadata={"source": "docling"},
    )


def test_looks_like_latex():
    from backend.tools.formula_tools import looks_like_latex

    assert looks_like_latex(r"E=mc^2")
    assert looks_like_latex(r"\frac{a}{b}")
    assert not looks_like_latex("")
    assert not looks_like_latex("uma foto de gato")
    assert not looks_like_latex("x" * 3000)


def test_looks_math_heuristic():
    from backend.tools.formula_tools import _looks_math

    # Casos reais capturados pelo OCR no benchmark
    assert _looks_math("E mc²")                      # símbolo forte ²
    assert _looks_math("-b±√b2 4ac x = 2a")          # ± e √
    assert _looks_math("e -T 2 dx π 2 0")            # π
    assert _looks_math("∑##")                        # ∑
    assert _looks_math("A 二 a c b d")               # matriz: tokens de 1 char
    assert _looks_math("x = 2 + 2 ^ 2")              # fracos suficientes

    assert not _looks_math("")
    assert not _looks_math("Entrada Processo Saida")
    assert not _looks_math("2021 2022 2023")
    assert not _looks_math(
        "A acessibilidade digital garante que pessoas com deficiencia "
        "possam perceber, compreender, navegar e interagir com conteudos"
    )


def test_cascade_routes_math_image_to_editor(reader, monkeypatch):
    monkeypatch.setattr(
        "backend.agents.reader_agent.try_extract_formula_locally",
        lambda image_bytes: r"E=mc^2",
    )
    tasks = reader._extract_mixed_tasks(Path("page.pdf"), [_image_region()], 1, 1)

    assert len(tasks) == 1
    assert tasks[0].agent_target == "editor"
    assert tasks[0].classification == "formula"
    assert tasks[0].text == r"$E=mc^2$"


def test_cascade_miss_falls_back_to_vision(reader, monkeypatch):
    monkeypatch.setattr(
        "backend.agents.reader_agent.try_extract_formula_locally",
        lambda image_bytes: "",
    )
    tasks = reader._extract_mixed_tasks(Path("page.pdf"), [_image_region()], 1, 1)

    assert len(tasks) == 1
    assert tasks[0].agent_target == "vision"
    assert tasks[0].classification == "embedded_image"


def test_cascade_disabled_by_setting(reader, monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "formula_image_cascade", False)
    monkeypatch.setattr(
        "backend.agents.reader_agent.try_extract_formula_locally",
        lambda image_bytes: (_ for _ in ()).throw(AssertionError("não deveria rodar")),
    )
    tasks = reader._extract_mixed_tasks(Path("page.pdf"), [_image_region()], 1, 1)

    assert tasks[0].agent_target == "vision"


def test_try_extract_formula_locally_skips_non_math(monkeypatch):
    from backend.tools import formula_tools

    monkeypatch.setattr(formula_tools, "ocr_image_text", lambda b: "gato na mesa")
    monkeypatch.setattr(
        formula_tools,
        "extract_latex_from_image",
        lambda b: (_ for _ in ()).throw(AssertionError("não deveria rodar")),
    )
    assert formula_tools.try_extract_formula_locally(b"img") == ""


def test_try_extract_formula_locally_runs_codeformula_on_math(monkeypatch):
    from backend.tools import formula_tools

    monkeypatch.setattr(
        formula_tools, "ocr_image_text", lambda b: "x = 2 + 2 ^ 2 = 6"
    )
    monkeypatch.setattr(
        formula_tools, "extract_latex_from_image", lambda b: r"x=2+2^2"
    )
    assert formula_tools.try_extract_formula_locally(b"img") == r"x=2+2^2"
