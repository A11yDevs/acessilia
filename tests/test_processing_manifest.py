from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.manifest.docling_extractor import DoclingExtraction
from backend.core.manifest.schema import processing_manifest_schema, validate_manifest


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "processing_manifest.schema.json"
)


class FakeDocument:
    def __init__(self) -> None:
        bbox = SimpleNamespace(
            l=10,
            t=20,
            r=200,
            b=80,
            coord_origin=SimpleNamespace(value="TOPLEFT"),
        )
        provenance = SimpleNamespace(page_no=1, bbox=bbox, charspan=(0, 6))
        self.items = [
            (
                SimpleNamespace(
                    label=None,
                    name="body",
                    self_ref="#/body",
                    parent=None,
                ),
                0,
            ),
            (
                SimpleNamespace(
                    label=SimpleNamespace(value="title"),
                    text="Documento de teste",
                    level=1,
                    prov=[provenance],
                    self_ref="#/texts/0",
                    parent=SimpleNamespace(cref="#/body"),
                    content_layer=SimpleNamespace(value="body"),
                ),
                1,
            ),
            (
                SimpleNamespace(
                    label=SimpleNamespace(value="picture"),
                    text="",
                    prov=[provenance],
                    self_ref="#/pictures/0",
                    parent=SimpleNamespace(cref="#/body"),
                    content_layer=SimpleNamespace(value="body"),
                ),
                1,
            ),
        ]
        self.pages = {
            1: SimpleNamespace(size=SimpleNamespace(width=595, height=842))
        }

    def iterate_items(self, **_: object):
        return iter(self.items)

    def num_pages(self) -> int:
        return 1


class FakeExtractor:
    def extract(self, _: Path) -> DoclingExtraction:
        timestamp = datetime(2026, 7, 27, tzinfo=timezone.utc)
        return DoclingExtraction(
            document=FakeDocument(),
            started_at=timestamp,
            completed_at=timestamp,
            duration_ms=5,
            version="2.test",
            configuration={"ocr": False},
        )


def test_agent_builds_valid_manifest_and_candidate_obligation(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    agent = InformationalStructuralAgent(extractor=FakeExtractor())  # type: ignore[arg-type]

    manifest = agent.process(source)
    payload = manifest.model_dump(mode="json", by_alias=True)

    assert payload["$schema"] == "urn:a11y-devs:schema:processing-manifest:1.1.0"
    assert manifest.summary.page_count == 1
    assert manifest.summary.element_count == 3
    assert manifest.elements[1].parent_id == manifest.elements[0].id
    assert manifest.obligations[0].kind == "describe-image"
    assert manifest.obligations[0].selected is False
    assert validate_manifest(payload, SCHEMA_PATH) == []


def test_generated_schema_is_draft_2020_12():
    schema = processing_manifest_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "urn:a11y-devs:schema:processing-manifest:1.1.0"
    assert schema["title"] == "ProcessingManifest"
    schema_on_disk = __import__("json").loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema_on_disk == schema


def test_manifest_rejects_unknown_target(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    manifest = InformationalStructuralAgent(
        extractor=FakeExtractor()  # type: ignore[arg-type]
    ).process(source)
    payload = manifest.model_dump(mode="json", by_alias=True)
    payload["obligations"][0]["target_ids"] = ["element-inexistente"]

    errors = validate_manifest(payload)

    assert any("alvos inexistentes" in error for error in errors)


def test_manifest_demotes_heading_inside_indented_callout_group(tmp_path: Path):
    class CalloutDocument:
        def __init__(self) -> None:
            self.pages = {
                1: SimpleNamespace(size=SimpleNamespace(width=600, height=800))
            }
            self.items = [
                (
                    SimpleNamespace(
                        label=None,
                        name="body",
                        self_ref="#/body",
                        parent=None,
                    ),
                    0,
                ),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="heading"),
                        text="CAPÍTULO 1",
                        level=1,
                        prov=[
                            SimpleNamespace(
                                page_no=1,
                                bbox=SimpleNamespace(
                                    l=40,
                                    t=20,
                                    r=560,
                                    b=52,
                                    coord_origin=SimpleNamespace(value="TOPLEFT"),
                                ),
                                charspan=(0, 10),
                            )
                        ],
                        self_ref="#/texts/0",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                    ),
                    1,
                ),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="heading"),
                        text="Atenção",
                        level=2,
                        prov=[
                            SimpleNamespace(
                                page_no=1,
                                bbox=SimpleNamespace(
                                    l=120,
                                    t=120,
                                    r=480,
                                    b=146,
                                    coord_origin=SimpleNamespace(value="TOPLEFT"),
                                ),
                                charspan=(0, 7),
                            )
                        ],
                        self_ref="#/texts/1",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                    ),
                    1,
                ),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="paragraph"),
                        text="Parágrafo 1 do callout.",
                        prov=[
                            SimpleNamespace(
                                page_no=1,
                                bbox=SimpleNamespace(
                                    l=120,
                                    t=150,
                                    r=480,
                                    b=176,
                                    coord_origin=SimpleNamespace(value="TOPLEFT"),
                                ),
                                charspan=(0, 24),
                            )
                        ],
                        self_ref="#/texts/2",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                    ),
                    1,
                ),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="paragraph"),
                        text="Parágrafo 2 do callout.",
                        prov=[
                            SimpleNamespace(
                                page_no=1,
                                bbox=SimpleNamespace(
                                    l=120,
                                    t=182,
                                    r=480,
                                    b=208,
                                    coord_origin=SimpleNamespace(value="TOPLEFT"),
                                ),
                                charspan=(0, 24),
                            )
                        ],
                        self_ref="#/texts/3",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                    ),
                    1,
                ),
            ]

        def iterate_items(self, **_: object):
            return iter(self.items)

        def num_pages(self) -> int:
            return 1

    class CalloutExtractor:
        def extract(self, _: Path) -> DoclingExtraction:
            timestamp = datetime(2026, 7, 27, tzinfo=timezone.utc)
            return DoclingExtraction(
                document=CalloutDocument(),
                started_at=timestamp,
                completed_at=timestamp,
                duration_ms=7,
                version="2.test",
                configuration={"ocr": False},
            )

    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    manifest = InformationalStructuralAgent(
        extractor=CalloutExtractor()  # type: ignore[arg-type]
    ).process(source)

    heading_like = [
        e for e in manifest.elements if (e.text or "").strip().lower() == "atenção"
    ]
    assert heading_like
    callout_title = heading_like[0]
    assert callout_title.type == "paragraph"
    assert callout_title.metadata.get("demoted_from_heading") is True
    assert callout_title.metadata.get("is_callout_title") is True

    linked_content = [
        e
        for e in manifest.elements
        if e.metadata.get("callout_id") == callout_title.metadata.get("callout_id")
    ]
    assert len(linked_content) >= 3


def test_manifest_preserves_code_text_without_sanitizer_side_effects(tmp_path: Path):
    class CodeDocument:
        def __init__(self) -> None:
            self.pages = {
                1: SimpleNamespace(size=SimpleNamespace(width=600, height=800))
            }
            self.items = [
                (
                    SimpleNamespace(
                        label=None,
                        name="body",
                        self_ref="#/body",
                        parent=None,
                    ),
                    0,
                ),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="code"),
                        text=(
                            "def demo():\r\n"
                            "    system: keep literal\r\n"
                            "    prompt: keep literal\r\n"
                            "    note = 'chain of thought'\r\n"
                            "    return note\r\n"
                        ),
                        prov=[
                            SimpleNamespace(
                                page_no=1,
                                bbox=SimpleNamespace(
                                    l=80,
                                    t=120,
                                    r=520,
                                    b=260,
                                    coord_origin=SimpleNamespace(value="TOPLEFT"),
                                ),
                                charspan=(0, 100),
                            )
                        ],
                        self_ref="#/code/0",
                        parent=SimpleNamespace(cref="#/body"),
                    ),
                    1,
                ),
            ]

        def iterate_items(self, **_: object):
            return iter(self.items)

        def num_pages(self) -> int:
            return 1

    class CodeExtractor:
        def extract(self, _: Path) -> DoclingExtraction:
            timestamp = datetime(2026, 7, 27, tzinfo=timezone.utc)
            return DoclingExtraction(
                document=CodeDocument(),
                started_at=timestamp,
                completed_at=timestamp,
                duration_ms=7,
                version="2.test",
                configuration={"ocr": False},
            )

    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    manifest = InformationalStructuralAgent(
        extractor=CodeExtractor()  # type: ignore[arg-type]
    ).process(source)

    code_elements = [e for e in manifest.elements if e.type == "code"]
    assert code_elements
    code_text = code_elements[0].text
    assert code_text is not None
    assert "\r" not in code_text
    assert "    system: keep literal" in code_text
    assert "    prompt: keep literal" in code_text
    assert "chain of thought" in code_text
    assert "[conteudo removido]" not in code_text


def test_manifest_extracts_table_ast_metadata_for_table_elements(tmp_path: Path):
    class TableDocument:
        def __init__(self) -> None:
            self.pages = {
                1: SimpleNamespace(size=SimpleNamespace(width=600, height=800))
            }
            self.items = [
                (
                    SimpleNamespace(
                        label=None,
                        name="body",
                        self_ref="#/body",
                        parent=None,
                    ),
                    0,
                ),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="table"),
                        text="",
                        rows=[["Nome", "Valor"], ["Taxa", "10%"]],
                        table={
                            "caption": "Resumo",
                            "header": [
                                {
                                    "cells": [
                                        {"text": "Nome", "scope": "col"},
                                        {"text": "Valor", "scope": "col"},
                                    ]
                                }
                            ],
                            "body": [
                                {
                                    "cells": [
                                        {"text": "Taxa"},
                                        {"text": "10%"},
                                    ]
                                }
                            ],
                        },
                        prov=[
                            SimpleNamespace(
                                page_no=1,
                                bbox=SimpleNamespace(
                                    l=80,
                                    t=120,
                                    r=520,
                                    b=260,
                                    coord_origin=SimpleNamespace(value="TOPLEFT"),
                                ),
                                charspan=(0, 10),
                            )
                        ],
                        self_ref="#/tables/0",
                        parent=SimpleNamespace(cref="#/body"),
                    ),
                    1,
                ),
            ]

        def iterate_items(self, **_: object):
            return iter(self.items)

        def num_pages(self) -> int:
            return 1

    class TableExtractor:
        def extract(self, _: Path) -> DoclingExtraction:
            timestamp = datetime(2026, 7, 27, tzinfo=timezone.utc)
            return DoclingExtraction(
                document=TableDocument(),
                started_at=timestamp,
                completed_at=timestamp,
                duration_ms=7,
                version="2.test",
                configuration={"ocr": False},
            )

    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    manifest = InformationalStructuralAgent(
        extractor=TableExtractor()  # type: ignore[arg-type]
    ).process(source)

    table_elements = [e for e in manifest.elements if e.type == "table"]
    assert table_elements
    table_metadata = table_elements[0].metadata

    assert "table_ast" in table_metadata
    assert table_metadata["table_ast"]["caption"] == "Resumo"
    assert table_metadata["table_ast"]["header"][0]["cells"][0]["text"] == "Nome"
    assert table_metadata["table_row_count"] == 2
    assert table_metadata["table_column_count"] == 2
    assert table_metadata["table_has_header"] is True
