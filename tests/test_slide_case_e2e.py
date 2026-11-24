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
as the scorecard already reports. Vision-written descriptions may vary between
runs, so the picture floor is deliberately below the full count.

Requires:
- ``CORE_BASE_URL`` pointing at a deployed core
- The dataset clone at ``tests/dataset`` (or ``ACESSILIA_TEST_DATASET_DIR``)
- ``pdftotext`` (poppler-utils) for the PDF/UA

``CORE_SLIDE_TIMEOUT`` (seconds, default 1500) bounds the job wait; the test
allows 1800 so the wait fails with its own message first::

    CORE_BASE_URL=https://www.acessilia3.inf.ufg.br/api/v1 \
        uv run pytest -m e2e tests/test_slide_case_e2e.py -v
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from scripts.bench import slide_case
from tests.core_api_support import download_token, poll, require_core, upload

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(1800)]

SLIDE_PDF = (
    Path(__file__).parent
    / "fixtures"
    / "presentations"
    / "grandezas-e-medidas-42pgs.pdf"
)
SLIDE_TIMEOUT = float(os.getenv("CORE_SLIDE_TIMEOUT", "1500"))
OUT = Path(__file__).resolve().parents[1] / "var" / "bench" / "slides" / "e2e"

#: The better staging output the slide case was written from (v4, before the
#: core move) kept 29 of the 31 pictures. A few may lose terms to the vision
#: model; below this the deck has lost what the reference delivered.
MIN_PICTURES_PASSED = 29

#: Objects whose text is read from the deck's text layer. Each one must pass in
#: at least one delivered output; the PDF/UA's stream order rescues a table row
#: that the layout interleaves.
REQUIRED_KINDS = ("text", "table-header", "table-row", "formula")


class DeckOutputs:
    """The two delivered outputs, their texts and scorecards."""

    def __init__(
        self,
        cards: dict[str, slide_case.Scorecard],
        texts: dict[str, str],
        expectations: dict,
    ) -> None:
        self.cards = cards
        self.texts = texts
        self.expectations = expectations

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
    require_core()

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
    OUT.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for ext, name in (("txt", "006.txt"), ("pdf_ua", "006.pdf_ua.pdf")):
        response = core_client.get(f"/download/{token}/{ext}")
        assert response.status_code == 200, f"{ext}: {response.text}"
        assert response.content, f"{ext} is empty"
        path = OUT / name
        path.write_bytes(response.content)
        written[ext] = path

    # The veraPDF report is only packaged when the audit ran; when present it
    # must describe a compliant PDF/UA (as in test_core_api_e2e.py).
    response = core_client.get(f"/download/{token}/zip")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        report_name = next(
            (name for name in archive.namelist() if name.endswith(".verapdf.json")),
            None,
        )
        if report_name is not None:
            report_bytes = archive.read(report_name)
            (OUT / "verapdf.json").write_bytes(report_bytes)
            report = json.loads(report_bytes)
            assert report.get("compliant") is True, report

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
    return DeckOutputs(cards, texts, expectations)


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


def test_text_tables_and_formulas_do_not_regress(deck: DeckOutputs) -> None:
    passed = deck.passed_by_kind()
    all_ids = deck.all_by_kind()
    missing = {
        kind: sorted(all_ids.get(kind, set()) - passed.get(kind, set()))
        for kind in REQUIRED_KINDS
    }
    assert all(not ids for ids in missing.values()), missing


def test_the_pictures_keep_their_descriptions(deck: DeckOutputs) -> None:
    pictures = deck.all_by_kind().get("image", set()) | deck.all_by_kind().get(
        "chemical-structure", set()
    )
    passed = deck.passed_by_kind().get("image", set()) | deck.passed_by_kind().get(
        "chemical-structure", set()
    )
    assert len(pictures & passed) >= MIN_PICTURES_PASSED, (
        f"{len(pictures & passed)}/{len(pictures)} pictures kept their terms"
    )


def test_no_fallback_or_broken_text_reaches_the_reader(deck: DeckOutputs) -> None:
    for ext, card in deck.cards.items():
        assert card.violations == {}, f"{ext}: {card.to_markdown()}"
