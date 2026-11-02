"""End-to-end run of the math reference case (requires Toolbox and a model provider).

Processes ``input/math-reference/velocidade-instantanea.pdf`` from the
acessilia-dataset clone through the core and scores it with
``scripts/bench/math_case.py``. The scorecard is written to
``var/bench/math-reference/e2e`` so a run can be compared with the numbers in a
PR description.

The assertions only lock what the core already delivers; the scorecard
reports the rest. Raise a floor here when a PR improves it.

Requires:
- Toolbox reachable at settings.toolbox_base_url, and the AI provider settings
- The dataset clone at tests/dataset (or ACESSILIA_TEST_DATASET_DIR)

    pytest tests/test_math_case_e2e.py -m e2e
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.config.settings import settings
from scripts.bench import math_case

OUT = math_case.REPO / "var" / "bench" / "math-reference" / "e2e"

#: Checks fixed by the legacy Unicode repair (ADR-0009/0010) that must not
#: regress, in both outputs.
LOCKED_TEXT_CHECKS = (
    "header-university", "header-department", "title", "subtitle", "spacing-accent",
)


@pytest.mark.e2e
def test_math_reference_case(monkeypatch):
    root = math_case.dataset_dir()
    pdf = root / math_case.CASE_DIR / math_case.CASE_PDF
    if not pdf.exists():
        pytest.skip(f"math reference case not found: {pdf}")
    rows, expectations = math_case.load_case(root)
    monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
    monkeypatch.setattr(settings, "pddl_execute_dry_run", False)

    canonical_path, txt_path, pdf_ua_path = asyncio.run(math_case._process(pdf, OUT, pdf_ua=True))
    card = math_case.score_case(
        rows,
        expectations,
        json.loads(canonical_path.read_text(encoding="utf-8")),
        txt_path.read_text(encoding="utf-8"),
        math_case.pdf_text(pdf_ua_path),
    )
    math_case._write(card, OUT)
    summary = card.summary()

    text = {c.id: c for c in card.text}
    failed = [
        f"{target}:{name}"
        for target in ("txt", "pdf_ua")
        for name in LOCKED_TEXT_CHECKS
        if not text[f"{target}:{name}"].passed
    ]
    assert failed == []
    assert summary["display_found"] == 100.0
    assert summary["display_with_mathml"] == 100.0
    assert summary["display_with_speech"] == 100.0

    structure = {check.id: check for check in card.structure}
    for name in ("ordered-list:p4", "ordered-list:p5"):
        assert structure[name].passed, structure[name].detail
    for target in ("txt", "pdf_ua"):
        check = text[f"{target}:negative-velocity"]
        assert check.passed, check.detail
