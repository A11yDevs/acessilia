"""End-to-end regression of the 42-slide deck (issue #615).

Processes ``grandezas-e-medidas-42pgs.pdf`` through the deployed core and
scores the TXT and PDF/UA it returns against acessilia-dataset's audited
``input/presentation-reference`` with ``scripts/bench/slide_case.py``. Each run
writes its outputs, scorecards and ``run.json`` metadata to a unique directory
under ``var/bench/slides/e2e``.

The case is the 006 deck, the one the core migration (#572) and the SDK
extraction (#470) left without a staging comparison. The dataset already
carries both the input (``input/006.pdf``) and its audited ground truth; this
suite uses the byte-identical copy in ``tests/fixtures/presentations`` as the
upload and checks it against the dataset copy when the clone is present.

The assertions are regression floors, not semantic approval: the legacy
``slide_case`` scorer checks text, table rows, formulas and picture terms.
Twelve slides have no text layer, so their tables and labels are OCR/vision
reads and can vary between runs; the floors are calibrated to the audited
dataset and the current staging output. The PDF/UA is held to zero known
pattern violations; the TXT has the exact known #869 inventory. Semantic
checks for chart associations, formula structure and object associations are
tracked separately in the benchmark issue, not claimed here.

Requires:
- ``CORE_BASE_URL`` pointing at a deployed core
- ``CORE_SLIDE_CASE=1``: this is a manual/slow case, never part of the ordinary gate
- The dataset clone at ``tests/dataset`` (or ``ACESSILIA_TEST_DATASET_DIR``),
  pinned to the audited ``presentation-reference`` revision
- ``pdftotext`` (poppler-utils) for the PDF/UA

``CORE_SLIDE_TIMEOUT`` (seconds, default 3600) bounds the job wait; the test
adds 600 seconds so the wait fails with its own message first::

    CORE_SLIDE_CASE=1 \
    CORE_BASE_URL=https://www.acessilia3.inf.ufg.br/api/v1 \
        uv run pytest -m e2e tests/test_slide_case_e2e.py -v
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
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
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
OUT = (
    Path(__file__).resolve().parents[1]
    / "var"
    / "bench"
    / "slides"
    / "e2e"
    / RUN_ID
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.timeout(SLIDE_TIMEOUT + 600),
]

#: The audited presentation reference merged in acessilia-dataset#12. The
#: hashes pin the CSV, expectations and audit report; a dataset clone that
#: follows a later un-audited revision fails before the upload.
DATASET_REVISION = "8e51a1f599056a6eb30dcbb05491f622a4d25eb1"
DATASET_HASHES = {
    "ground_truth.csv": "f9fd718727dc144379cebd0d64927577c0e47763fb835ae38cf4a48e036a91cf",
    "expectations.json": "200d972dd196a5210fd2e90bfb767d140cd31d1cc5e11f6c0881e5a7b1e022a4",
    "AUDIT.md": "5f23b65d448f18394aad6741713bc1ec15feb8b76749d1d4f479e728675eb8a1",
    "validate.py": "bf6a9ce1af62c9e2cbd3a315d95197ca1cc6f5d2ac064f1c933b077e8d4904ed",
}
SLIDE_PDF_SHA256 = "ce9874fd3219241766772904c84f7eed3e340befa9a6beee6ca206308b8a549f"
BASELINE = (
    Path(__file__).parent
    / "fixtures"
    / "presentations"
    / "staging-baseline.json"
)

#: Per-format floors from the audited reference and the 2026-11-25 staging
#: output. They are prospective regression floors, not a claim of full
#: coverage; #870 tracks the missing image-only table rows. The margins leave
#: room for the documented OCR/vision variance.
MIN_BY_FORMAT = {
    "txt": {"text": 126, "table-header": 7, "table-row": 60, "formula": 12},
    "pdf_ua": {"text": 122, "table-header": 7, "table-row": 65, "formula": 12},
}
MIN_IMAGES_BY_FORMAT = {"txt": 29, "pdf_ua": 29}
#: One chemical structure is currently missing in both outputs; tracked in
#: the benchmark/product follow-up rather than hidden as a full pass.
MIN_CHEMICAL_STRUCTURES_BY_FORMAT = {"txt": 4, "pdf_ua": 4}

#: Exact known TXT violations from #869. A new page or a count above these
#: fails; the PDF/UA has no such tolerance.
KNOWN_TXT_VIOLATIONS = {
    3: Counter({"english-table-row": 1}),
    4: Counter({"english-table-row": 1}),
    5: Counter({"english-table-row": 1}),
    6: Counter({"english-table-row": 1}),
    8: Counter({"english-table-row": 1}),
    10: Counter({"english-table-row": 1, "label-list-alt": 1}),
    15: Counter({"english-table-row": 1}),
    32: Counter({"english-table-row": 1}),
    33: Counter({"english-table-row": 1}),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _known_pdf_ua_failure(report: dict) -> bool:
    """The one .notdef failure tracked in #868, and nothing else."""
    failures = report.get("failures") or []
    if len(failures) != 1:
        return False
    failure = failures[0]
    return failure.get("clause") == "7.21.8" and "notdef" in json.dumps(
        failure, ensure_ascii=False
    ).lower()


class DeckOutputs:
    """The two delivered outputs, their texts and scorecards."""

    def __init__(
        self,
        cards: dict[str, slide_case.Scorecard],
        texts: dict[str, str],
        expectations: dict,
        verapdf: dict | None,
        run: dict,
    ) -> None:
        self.cards = cards
        self.texts = texts
        self.expectations = expectations
        self.verapdf = verapdf
        self.run = run

    def passed_by_kind(self, ext: str) -> dict[str, set[str]]:
        """Ids that passed in this output, per ground-truth kind."""
        passed: dict[str, set[str]] = {}
        for result in self.cards[ext].objects:
            if result.passed:
                passed.setdefault(result.kind, set()).add(result.id)
        return passed

    def all_by_kind(self, ext: str) -> dict[str, set[str]]:
        all_ids: dict[str, set[str]] = {}
        for result in self.cards[ext].objects:
            all_ids.setdefault(result.kind, set()).add(result.id)
        return all_ids


@pytest.fixture(scope="module")
def deck(core_client) -> DeckOutputs:
    """One real deck job, scored as TXT and as PDF/UA."""
    if os.getenv("CORE_SLIDE_CASE") != "1":
        pytest.skip("set CORE_SLIDE_CASE=1 to run the manual 42-slide deck case")

    root = slide_case.dataset_dir()
    case = root / slide_case.CASE_DIR
    if not (case / "ground_truth.csv").exists():
        pytest.skip(
            "presentation-reference not found: clone A11yDevs/acessilia-dataset "
            "into tests/dataset or set ACESSILIA_TEST_DATASET_DIR"
        )
    assert _sha256(SLIDE_PDF) == SLIDE_PDF_SHA256, "the local presentation fixture changed"
    for name, expected in DATASET_HASHES.items():
        path = case / name
        assert path.is_file(), f"the audited dataset file is missing: {path}"
        assert _sha256(path) == expected, (
            f"{path} is not the audited reference ({DATASET_REVISION})"
        )
    dataset_pdf = root / "input" / slide_case.CASE_PDF
    if dataset_pdf.exists():
        assert _sha256(dataset_pdf) == SLIDE_PDF_SHA256, (
            "the presentation fixture and the dataset input drifted apart"
        )
    rows, expectations = slide_case.load_case(root)
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext (poppler-utils) is required to score the PDF/UA output")
    require_core()
    OUT.mkdir(parents=True)

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    health = core_client.get("/health").json()
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
    texts = {ext: slide_case.read_output(path) for ext, path in written.items()}
    for ext, card in cards.items():
        (OUT / f"scorecard-{ext}.json").write_text(
            json.dumps(card.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (OUT / f"scorecard-{ext}.md").write_text(card.to_markdown(), encoding="utf-8")

    run = {
        "dataset_revision": DATASET_REVISION,
        "dataset_hashes": DATASET_HASHES,
        "core_base_url": os.getenv("CORE_BASE_URL", "").strip().rstrip("/"),
        "git_commit": health.get("git_commit"),
        "image_tag": health.get("image_tag"),
        "task_id": receipt["task_id"],
        "started_at": started_at,
        "duration_seconds": round(time.monotonic() - started, 1),
        "status": status,
    }
    (OUT / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return DeckOutputs(cards, texts, expectations, verapdf, run)


def test_the_deck_keeps_all_42_slides(deck: DeckOutputs) -> None:
    for ext, card in deck.cards.items():
        assert card.slides_found == 42, f"{ext}: {card.to_markdown()}"
        numbers = [
            int(match.group(1))
            for match in slide_case.SLIDE_HEADING.finditer(deck.texts[ext])
        ]
        assert numbers == list(range(1, 43)), f"{ext}: slide headings are {numbers}"


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
    for ext, floors in MIN_BY_FORMAT.items():
        passed = deck.passed_by_kind(ext)
        all_ids = deck.all_by_kind(ext)
        for kind, minimum in floors.items():
            ids = all_ids.get(kind, set())
            assert ids, f"{ext}: the dataset has no {kind} ground-truth rows"
            kept = ids & passed.get(kind, set())
            assert len(kept) >= minimum, (
                f"{ext}: {len(kept)}/{len(ids)} {kind} objects passed; "
                f"floor is {minimum}"
            )


def test_no_baseline_object_is_lost(deck: DeckOutputs) -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert baseline["dataset_revision"] == DATASET_REVISION
    for ext, kinds in baseline["formats"].items():
        passed = deck.passed_by_kind(ext)
        for kind, ids in kinds.items():
            lost = sorted(set(ids) - passed.get(kind, set()))
            assert not lost, (
                f"{ext}: baseline {kind} objects regressed: {lost}; "
                f"update {BASELINE.name} only with evidence"
            )


def test_the_pictures_keep_their_descriptions(deck: DeckOutputs) -> None:
    for ext in deck.cards:
        all_ids = deck.all_by_kind(ext)
        passed = deck.passed_by_kind(ext)
        for kind, minimum in (
            ("image", MIN_IMAGES_BY_FORMAT[ext]),
            ("chemical-structure", MIN_CHEMICAL_STRUCTURES_BY_FORMAT[ext]),
        ):
            ids = all_ids.get(kind, set())
            kept = ids & passed.get(kind, set())
            assert len(kept) >= minimum, (
                f"{ext}: {len(kept)}/{len(ids)} {kind} descriptions kept their terms"
            )


def test_no_fallback_or_broken_text_reaches_the_reader(deck: DeckOutputs) -> None:
    pdf = deck.cards["pdf_ua"]
    assert pdf.violations == {}, pdf.to_markdown()
    txt = deck.cards["txt"]
    for page, names in txt.violations.items():
        actual = Counter(names)
        allowed = KNOWN_TXT_VIOLATIONS.get(page, Counter())
        assert not (actual - allowed), (
            f"TXT slide {page}: {dict(actual)}; allowed known #869 is {dict(allowed)}"
        )


def test_the_pdf_ua_is_compliant(deck: DeckOutputs) -> None:
    assert deck.verapdf is not None, "the delivered ZIP has no veraPDF report"
    if deck.verapdf.get("compliant") is True:
        return
    if _known_pdf_ua_failure(deck.verapdf):
        pytest.xfail("known .notdef glyph in the PDF/UA, issue #868")
    pytest.fail(f"new PDF/UA failures: {deck.verapdf}")
