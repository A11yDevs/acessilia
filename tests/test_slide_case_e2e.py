"""End-to-end regression of the 42-slide deck (issue #615).

Processes ``grandezas-e-medidas-42pgs.pdf`` through the deployed core and
scores the TXT and PDF/UA it returns against acessilia-dataset's
``input/presentation-reference`` with ``scripts/bench/slide_case.py``. The
outputs and scorecards are written to ``var/bench/slides/e2e`` so a run can be
attached to a PR.

The case is the 006 deck, the one the core migration (#572) and the SDK
extraction (#470) left without a staging comparison. The dataset already
carries both the input (``input/006.pdf``) and its ground truth; this suite
uses the byte-identical copy in ``tests/fixtures/presentations`` as the upload
and checks it against the dataset copy when the clone is present.

The assertions lock what the pre-migration reference delivered: every slide
and its title, the text, tables and formulas in their slide, and no fallback
that hides a picture. A table row may be found in the PDF/UA's stream order,
as the scorecard already reports. Twelve slides have no text layer; their
tables and labels are read from the image (OCR/vision), so those objects can
vary between runs even when the text-layer objects do not. The picture floor
is deliberately below the full count for the same reason.

Requires:
- ``CORE_BASE_URL`` pointing at a deployed core
- The dataset clone at ``tests/dataset`` (or ``ACESSILIA_TEST_DATASET_DIR``)
- ``pdftotext`` (poppler-utils) for the PDF/UA

``CORE_SLIDE_TIMEOUT`` (seconds, default 3600) bounds the job wait; the test
adds 600 seconds so the wait fails with its own message first. The deck has 36
images and takes several minutes on staging, so this is a manual/slow case,
not part of the scheduled gate::

    CORE_BASE_URL=https://www.acessilia3.inf.ufg.br/api/v1 \
        uv run pytest -m e2e tests/test_slide_case_e2e.py -v
"""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.bench import slide_case
from tests.core_api_support import download_token, poll, require_core, upload

SLIDE_PDF = (
    Path(__file__).parent
    / "fixtures"
    / "presentations"
    / "grandezas-e-medidas-42pgs.pdf"
)
SLIDE_TIMEOUT = float(os.getenv("CORE_SLIDE_TIMEOUT", "3600"))
OUT = Path(__file__).resolve().parents[1] / "var" / "bench" / "slides" / "e2e"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.timeout(SLIDE_TIMEOUT + 600),
]

#: The better staging output the slide case was written from (v4, before the
#: core move) kept 29 of the 31 image descriptions. The five chemical
#: structures are scored separately: #284 is exactly the regression where a
#: drawn molecule loses its description.
MIN_IMAGES_PASSED = 29
MIN_CHEMICAL_STRUCTURES_PASSED = 5

#: Floors for the objects read from the deck. The image-only slides are
#: OCR/vision reads and the current staging output still misses table rows
#: there (#870); the floors catch a collapse without turning model variance
#: into a failed run. The PDF/UA's stream order rescues a table row that the
#: layout interleaves.
MIN_BY_KIND = {
    "text": 60,
    "table-header": 11,
    "table-row": 60,
    "formula": 10,
}

#: Known TXT table linearization defects tracked in #869. The PDF/UA is held
#: to zero; the TXT keeps its rows but uses English `Row N:` labels and folds
#: some cells into a label list.
KNOWN_TXT_VIOLATIONS = frozenset({"english-table-row", "label-list-alt"})


class DeckOutputs:
    """The two delivered outputs, their texts and scorecards."""

    def __init__(
        self,
        cards: dict[str, slide_case.Scorecard],
        texts: dict[str, str],
        expectations: dict,
        verapdf: dict | None,
    ) -> None:
        self.cards = cards
        self.texts = texts
        self.expectations = expectations
        self.verapdf = verapdf

    def passed_by_kind(self) -> dict[str, set[str]]:
        """Ids that passed in at least one output, per ground-truth kind."""
        passed: dict[str, set[str]] = {}
        for card in self.cards.values():
            for result in card.objects:
                if result.passed:
                    passed.setdefault(result.kind, set()).add(result.id)
        return passed

    def all_by_kind(self) -> dict[str, set[str]]:
        all_ids: dict[str, set[str]] = {}
        for card in self.cards.values():
            for result in card.objects:
                all_ids.setdefault(result.kind, set()).add(result.id)
        return all_ids


@pytest.fixture(scope="module")
def deck(core_client) -> DeckOutputs:
    """One real deck job, scored as TXT and as PDF/UA."""
    root = slide_case.dataset_dir()
    if not (root / slide_case.CASE_DIR / "ground_truth.csv").exists():
        pytest.skip(
            "presentation-reference not found: clone A11yDevs/acessilia-dataset "
            "into tests/dataset or set ACESSILIA_TEST_DATASET_DIR"
        )
    dataset_pdf = root / "input" / slide_case.CASE_PDF
    if dataset_pdf.exists():
        assert dataset_pdf.read_bytes() == SLIDE_PDF.read_bytes(), (
            "the presentation fixture and the dataset input drifted apart"
        )
    rows, expectations = slide_case.load_case(root)
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext (poppler-utils) is required to score the PDF/UA output")
    require_core()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)

    response = upload(
        core_client,
        SLIDE_PDF.read_bytes(),
        SLIDE_PDF.name,
        media_type="application/pdf",
    )
    assert response.status_code == 202, response.text
    receipt = response.json()
    status = poll(
        core_client,
        receipt["task_id"],
        receipt["job_token"],
        timeout=SLIDE_TIMEOUT,
    )
    assert status["status"] == "done", status
    assert not status.get("erros"), status

    token = download_token(status)
    written: dict[str, Path] = {}
    for ext, name in (("txt", "006.txt"), ("pdf_ua", "006.pdf_ua.pdf")):
        response = core_client.get(f"/download/{token}/{ext}")
        assert response.status_code == 200, f"{ext}: {response.text}"
        assert response.content, f"{ext} is empty"
        path = OUT / name
        path.write_bytes(response.content)
        written[ext] = path

    # The veraPDF report is only packaged when the audit ran. Keep it for the
    # compliance test; scoring must still run when it is absent or failing.
    response = core_client.get(f"/download/{token}/zip")
    assert response.status_code == 200, response.text
    verapdf = None
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        report_name = next(
            (name for name in archive.namelist() if name.endswith(".verapdf.json")),
            None,
        )
        if report_name is not None:
            report_bytes = archive.read(report_name)
            (OUT / "verapdf.json").write_bytes(report_bytes)
            verapdf = json.loads(report_bytes)

    cards = {
        ext: slide_case.score_output(rows, expectations, path)
        for ext, path in written.items()
    }
    texts = {
        ext: slide_case.read_output(path) for ext, path in written.items()
    }
    for ext, card in cards.items():
        (OUT / f"scorecard-{ext}.json").write_text(
            json.dumps(card.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (OUT / f"scorecard-{ext}.md").write_text(card.to_markdown(), encoding="utf-8")
    return DeckOutputs(cards, texts, expectations, verapdf)


def test_the_deck_keeps_all_42_slides(deck: DeckOutputs) -> None:
    for ext, card in deck.cards.items():
        assert card.slides_found == 42, f"{ext}: {card.to_markdown()}"


def test_every_slide_title_stays_on_its_slide(deck: DeckOutputs) -> None:
    structure = deck.expectations["structure"]
    for ext, text in deck.texts.items():
        sections = slide_case.split_slides(text)
        title = structure["deck_title"]["text"]
        assert slide_case.normalize(title) in slide_case.normalize(sections[1]), (
            f"{ext}: the deck title left slide 1"
        )
        for expected in structure["slide_titles"]:
            page = expected["page"]
            assert slide_case.normalize(expected["title"]) in slide_case.normalize(
                sections[page]
            ), f"{ext}: the title of slide {page} is not on slide {page}"


def test_text_tables_and_formulas_stay_above_the_regression_floor(
    deck: DeckOutputs,
) -> None:
    passed = deck.passed_by_kind()
    all_ids = deck.all_by_kind()
    # Do not let a renamed or missing ground-truth kind turn the floors below
    # into a vacuous pass.
    for kind, minimum in MIN_BY_KIND.items():
        ids = all_ids.get(kind, set())
        assert ids, f"the dataset has no {kind} ground-truth rows"
        kept = ids & passed.get(kind, set())
        assert len(kept) >= minimum, (
            f"{len(kept)}/{len(ids)} {kind} objects passed; floor is {minimum}"
        )


def test_the_pictures_keep_their_descriptions(deck: DeckOutputs) -> None:
    all_ids = deck.all_by_kind()
    passed = deck.passed_by_kind()
    for kind, minimum in (
        ("image", MIN_IMAGES_PASSED),
        ("chemical-structure", MIN_CHEMICAL_STRUCTURES_PASSED),
    ):
        ids = all_ids.get(kind, set())
        kept = ids & passed.get(kind, set())
        assert len(kept) >= minimum, (
            f"{len(kept)}/{len(ids)} {kind} descriptions kept their terms"
        )


def test_no_fallback_or_broken_text_reaches_the_reader(deck: DeckOutputs) -> None:
    pdf = deck.cards["pdf_ua"]
    assert pdf.violations == {}, pdf.to_markdown()
    txt = deck.cards["txt"]
    unknown = {
        page: [name for name in names if name not in KNOWN_TXT_VIOLATIONS]
        for page, names in txt.violations.items()
        if any(name not in KNOWN_TXT_VIOLATIONS for name in names)
    }
    assert unknown == {}, f"TXT: {unknown}; known #869 is {sorted(KNOWN_TXT_VIOLATIONS)}"


@pytest.mark.xfail(
    strict=True,
    reason="known .notdef glyph in the PDF/UA, issue #868",
)
def test_the_pdf_ua_is_compliant(deck: DeckOutputs) -> None:
    assert deck.verapdf is not None, "the delivered ZIP has no veraPDF report"
    assert deck.verapdf.get("compliant") is True, deck.verapdf
