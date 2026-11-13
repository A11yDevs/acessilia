"""The deterministic transforms must reach the manifest and the payload.

Issue #474: line-number extraction, verse chunking and the tail join counted
their work in ``metadata`` and reported success while the element texts and the
element list stayed as they were. These tests check the manifest elements and
the structured payload after each handler, not only ``success``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.manifest.models import (
    BoundingBox,
    ProcessingManifest,
    Provenance,
)
from backend.core.pipeline.handlers.text import (
    _handle_chunk_verse_method,
    _handle_extract_line_numbers_method,
    _handle_tailjoin_method,
)
from backend.core.pipeline.payload import build_pddl_structured_payload

from tests.pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)

#: Long paragraph with the marginal numbers 3964, 3969 and 3974 (step 5).
_LONG_VERSE_TEXT = (
    "Primeira linha do poema com bastante texto para passar do limite minimo "
    "de deteccao 3964 e continuar.\n"
    "Segunda linha do poema, tambem longa o suficiente para o detector de "
    "numeros de linha marginais considerar o bloco 3969 como candidato.\n"
    "Terceira linha do poema, mantendo o comprimento necessario para que a "
    "progressao aritmetica seja reconhecida 3974 pelo detector.\n"
)

#: Record-shaped block split at the blank line into two stanzas.
_VERSE_TEXT = (
    "Capitulo 1 .......... 10\n"
    "Capitulo 2 .......... 25\n"
    "\n"
    "Capitulo 3 .......... 40\n"
    "Capitulo 4 .......... 55\n"
    "Capitulo 5 .......... 70\n"
)

#: Body block long enough to stay out of the short-tail window.
_TAIL_BODY = (
    "Um paragrafo de corpo bem mais longo que o limite de bloco curto usado aqui."
)


def _box() -> Provenance:
    return Provenance(
        page_number=1,
        bbox=BoundingBox(
            left=10, top=20, right=500, bottom=700, coord_origin="TOPLEFT"
        ),
        char_start=0,
        char_end=10,
    )


def _payload(tmp_path: Path, manifest: ProcessingManifest) -> dict:
    plan, _ = _orchestrator()._build_plan(manifest)
    return build_pddl_structured_payload(
        file_path=tmp_path / "doc.pdf",
        manifest=manifest,
        plan=plan,
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )


def _assert_manifest_is_valid(manifest: ProcessingManifest) -> None:
    ProcessingManifest.model_validate(manifest.model_dump(mode="json"))


class TestLineNumbersReachTheManifest:
    def test_the_text_loses_the_numbers_and_metadata_keeps_them(self, tmp_path) -> None:
        element = _element("el-1", "paragraph", text=_LONG_VERSE_TEXT)
        element.provenance = [_box()]
        manifest = _manifest(
            [element],
            [_obligation("extract-line-numbers", ["el-1"], ["line-number-extractor"])],
        )

        result = _handle_extract_line_numbers_method(manifest, "o-1")

        assert result.success is True
        assert element.text is not None
        for number in ("3964", "3969", "3974"):
            assert number not in element.text
        assert element.metadata["line_numbers"] == ["3964", "3969", "3974"]
        # The target keeps its id and its provenance.
        assert element.id == "el-1"
        assert element.provenance[0].bbox == _box().bbox
        _assert_manifest_is_valid(manifest)

        block = _payload(tmp_path, manifest)["pages"][0]["blocks"][0]
        assert "3964" not in block["text"]
        assert block["metadata"]["line_numbers"] == ["3964", "3969", "3974"]

    def test_it_fails_when_there_is_no_number_to_extract(self) -> None:
        element = _element("el-1", "paragraph", text="Um paragrafo comum, sem numeros.")
        manifest = _manifest(
            [element],
            [_obligation("extract-line-numbers", ["el-1"], ["line-number-extractor"])],
        )

        result = _handle_extract_line_numbers_method(manifest, "o-1")

        assert result.success is False
        assert element.text == "Um paragrafo comum, sem numeros."
        assert "line_numbers" not in element.metadata


class TestPageMembershipSurvivesTheTransforms:
    def test_an_element_owned_by_the_page_without_page_number_stays_in_the_payload(
        self, tmp_path
    ) -> None:
        stable = _element("el-1", "paragraph", text="Texto estavel da pagina.")
        stable.page_number = None
        verse = _element("el-2", "paragraph", text=_VERSE_TEXT, reading_order=2)
        verse.page_number = None
        manifest = _manifest(
            [stable, verse],
            [_obligation("chunk-verse", ["el-2"], ["verse-chunker"])],
        )

        result = _handle_chunk_verse_method(manifest, "o-1")

        assert result.success is True
        # The page owned el-1 through element_ids, not through page_number.
        assert manifest.pages[0].element_ids == ["el-1", "el-2", "el-2-verse-1"]
        texts = [
            block["text"]
            for page in _payload(tmp_path, manifest)["pages"]
            for block in page["blocks"]
        ]
        assert "Texto estavel da pagina." in texts
        _assert_manifest_is_valid(manifest)

    def test_a_page_member_without_page_number_survives_the_join(
        self, tmp_path
    ) -> None:
        body = _element("el-1", "paragraph", text=_TAIL_BODY, reading_order=1)
        header = _element("el-2", "paragraph", text="Capitulo 1", reading_order=2)
        number = _element("el-3", "paragraph", text="42", reading_order=3)
        for element in (body, header, number):
            element.page_number = None
        manifest = _manifest(
            [body, header, number],
            [_obligation("join-tail-blocks", ["el-2", "el-3"], ["tailjoin"])],
        )

        result = _handle_tailjoin_method(manifest, "o-1")

        assert result.success is True
        assert manifest.pages[0].element_ids == ["el-1", "el-2"]
        texts = [
            block["text"]
            for page in _payload(tmp_path, manifest)["pages"]
            for block in page["blocks"]
        ]
        assert texts == [_TAIL_BODY, "Capitulo 1 42"]
        _assert_manifest_is_valid(manifest)


class TestVerseChunksReachTheManifest:
    def test_the_chunks_replace_the_element_in_the_payload(self, tmp_path) -> None:
        element = _element("el-1", "paragraph", text=_VERSE_TEXT)
        element.provenance = [_box()]
        manifest = _manifest(
            [element],
            [_obligation("chunk-verse", ["el-1"], ["verse-chunker"])],
        )

        result = _handle_chunk_verse_method(manifest, "o-1")

        assert result.success is True
        assert [item.id for item in manifest.elements] == ["el-1", "el-1-verse-1"]
        assert [item.reading_order for item in manifest.elements] == [1, 2]
        assert manifest.pages[0].element_ids == ["el-1", "el-1-verse-1"]
        assert manifest.summary.element_count == 2
        first, second = manifest.elements
        assert "Capitulo 1" in (first.text or "")
        assert "Capitulo 2" in (first.text or "")
        assert "Capitulo 3" in (second.text or "")
        assert "Capitulo 1" not in (second.text or "")
        # The split keeps the source id on the first chunk and tracks the rest.
        assert set(manifest.obligations[0].target_ids) == {
            "el-1",
            "el-1-verse-1",
        }
        assert first.metadata["verse"] is True
        assert second.metadata["split_from"] == "el-1"
        assert second.metadata["chunk_index"] == 1
        assert second.provenance[0].bbox is not None
        assert second.provenance[0].bbox.top > _box().bbox.top
        _assert_manifest_is_valid(manifest)

        blocks = _payload(tmp_path, manifest)["pages"][0]["blocks"]
        assert [block["text"] for block in blocks] == [first.text, second.text]
        assert all(block["metadata"]["verse"] is True for block in blocks)

    def test_it_fails_when_the_target_is_not_a_record(self) -> None:
        element = _element("el-1", "paragraph", text="A short paragraph.")
        manifest = _manifest(
            [element],
            [_obligation("chunk-verse", ["el-1"], ["verse-chunker"])],
        )

        result = _handle_chunk_verse_method(manifest, "o-1")

        assert result.success is False
        assert [item.id for item in manifest.elements] == ["el-1"]


class TestTailJoinReachesTheManifest:
    def _manifest(self, targets: list[str]) -> ProcessingManifest:
        body = _element("el-1", "paragraph", text=_TAIL_BODY, reading_order=1)
        header = _element("el-2", "paragraph", text="Capitulo 1", reading_order=2)
        number = _element("el-3", "paragraph", text="42", reading_order=3)
        return _manifest(
            [body, header, number],
            [_obligation("join-tail-blocks", targets, ["tailjoin"])],
        )

    def test_the_joined_text_replaces_the_tail_and_drops_the_extra_elements(
        self, tmp_path
    ) -> None:
        manifest = self._manifest(["el-2", "el-3"])

        result = _handle_tailjoin_method(manifest, "o-1")

        assert result.success is True
        assert [item.id for item in manifest.elements] == ["el-1", "el-2"]
        assert [item.reading_order for item in manifest.elements] == [1, 2]
        assert manifest.elements[1].text == "Capitulo 1 42"
        assert manifest.elements[1].metadata["tailjoined"] is True
        assert manifest.pages[0].element_ids == ["el-1", "el-2"]
        assert manifest.summary.element_count == 2
        # The obligation pointed at both tail blocks and now points at the survivor.
        assert manifest.obligations[0].target_ids == ["el-2"]
        _assert_manifest_is_valid(manifest)

        blocks = _payload(tmp_path, manifest)["pages"][0]["blocks"]
        assert [block["text"] for block in blocks] == [_TAIL_BODY, "Capitulo 1 42"]

    def test_the_joined_element_keeps_the_provenance_of_the_dropped_ones(self) -> None:
        header_box = BoundingBox(
            left=100, top=10, right=200, bottom=20, coord_origin="TOPLEFT"
        )
        number_box = BoundingBox(
            left=280, top=790, right=310, bottom=800, coord_origin="TOPLEFT"
        )
        body = _element("el-1", "paragraph", text=_TAIL_BODY, reading_order=1)
        header = _element("el-2", "paragraph", text="Header", reading_order=2)
        header.provenance = [
            Provenance(page_number=1, bbox=header_box, char_start=0, char_end=6)
        ]
        number = _element("el-3", "paragraph", text="42", reading_order=3)
        number.provenance = [
            Provenance(page_number=1, bbox=number_box, char_start=0, char_end=2)
        ]
        manifest = _manifest(
            [body, header, number],
            [_obligation("join-tail-blocks", ["el-2", "el-3"], ["tailjoin"])],
        )

        result = _handle_tailjoin_method(manifest, "o-1")

        assert result.success is True
        survivor = manifest.elements[1]
        assert survivor.text == "Header 42"
        assert [entry.bbox for entry in survivor.provenance] == [
            header_box,
            number_box,
        ]
        # The spans move with the text instead of pointing into either source.
        assert [
            (entry.char_start, entry.char_end) for entry in survivor.provenance
        ] == [(0, 6), (7, 9)]
        _assert_manifest_is_valid(manifest)

    def test_a_child_reparented_by_the_join_updates_its_parent_ref(self) -> None:
        body = _element("el-1", "paragraph", text=_TAIL_BODY, reading_order=1)
        header = _element("el-2", "paragraph", text="Capitulo 1", reading_order=2)
        header.source_ref = "#/texts/0"
        number = _element("el-3", "paragraph", text="42", reading_order=3)
        number.source_ref = "#/texts/1"
        child = _element("el-4", "picture", reading_order=4)
        child.parent_id = "el-3"
        child.parent_ref = "#/texts/1"
        manifest = _manifest(
            [body, header, number, child],
            [_obligation("join-tail-blocks", ["el-2", "el-3"], ["tailjoin"])],
        )

        result = _handle_tailjoin_method(manifest, "o-1")

        assert result.success is True
        survivor = next(item for item in manifest.elements if item.id == "el-2")
        reparented = next(item for item in manifest.elements if item.id == "el-4")
        assert reparented.parent_id == survivor.id
        assert reparented.parent_ref == survivor.source_ref == "#/texts/0"
        assert reparented.metadata["original_parent_ref"] == "#/texts/1"
        _assert_manifest_is_valid(manifest)

    def test_it_fails_when_the_targets_are_not_the_page_tail(self) -> None:
        manifest = self._manifest(["el-3"])

        result = _handle_tailjoin_method(manifest, "o-1")

        assert result.success is False
        assert [item.id for item in manifest.elements] == ["el-1", "el-2", "el-3"]
        assert manifest.elements[1].text == "Capitulo 1"


class TestTheExecutorAppliesTheTransform:
    """The bug was success without a manifest change; run the real executor."""

    @staticmethod
    def _manifest(case: str) -> ProcessingManifest:
        if case == "line-numbers":
            return _manifest(
                [_element("el-1", "paragraph", text=_LONG_VERSE_TEXT)],
                [
                    _obligation(
                        "extract-line-numbers", ["el-1"], ["line-number-extractor"]
                    )
                ],
            )
        if case == "verse":
            return _manifest(
                [_element("el-1", "paragraph", text=_VERSE_TEXT)],
                [_obligation("chunk-verse", ["el-1"], ["verse-chunker"])],
            )
        return _manifest(
            [
                _element("el-1", "paragraph", text=_TAIL_BODY, reading_order=1),
                _element("el-2", "paragraph", text="Capitulo 1", reading_order=2),
                _element("el-3", "paragraph", text="42", reading_order=3),
            ],
            [_obligation("join-tail-blocks", ["el-2", "el-3"], ["tailjoin"])],
        )

    @pytest.mark.parametrize(
        ("case", "expected_ids"),
        [
            ("line-numbers", ["el-1"]),
            ("verse", ["el-1", "el-1-verse-1"]),
            ("tailjoin", ["el-1", "el-2"]),
        ],
    )
    def test_the_plan_completes_and_changes_the_manifest(
        self, case: str, expected_ids: list[str]
    ) -> None:
        orchestrator = _orchestrator()
        manifest = self._manifest(case)
        plan, _ = orchestrator._build_plan(manifest)

        updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)

        assert report.status == "completed"
        assert updated.obligations[0].status == "satisfied"
        assert [item.id for item in updated.elements] == expected_ids
        _assert_manifest_is_valid(updated)

