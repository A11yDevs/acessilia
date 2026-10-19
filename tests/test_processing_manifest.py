"""The processing manifest built from a Toolbox structural extraction.

The Toolbox is the only extractor (docs/adr/0003). Its elements already carry
callouts, code text and table structure; the core validates them and derives
its own observations and obligations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.manifest.builder import build_processing_manifest
from backend.core.manifest.schema import processing_manifest_schema, validate_manifest
from backend.core.manifest.toolbox_extractor import ToolboxExtraction


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "processing_manifest.schema.json"
)
TOOLBOX_RESPONSE = Path(__file__).parent / "fixtures" / "toolbox-v2-contract.json"


class FakeExtractor:
    """Returns a recorded Toolbox ``document.structure.extract`` response."""

    def extract(self, _: Path) -> ToolboxExtraction:
        timestamp = datetime(2026, 7, 27, tzinfo=timezone.utc)
        return ToolboxExtraction(
            document=json.loads(TOOLBOX_RESPONSE.read_text(encoding="utf-8")),
            started_at=timestamp,
            completed_at=timestamp,
            duration_ms=5,
            version="toolbox-test",
            configuration={"ocr": False},
        )


def _manifest(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    return InformationalStructuralAgent(extractor=FakeExtractor()).process(source)


def test_agent_builds_valid_manifest_and_candidate_obligation(tmp_path: Path):
    manifest = _manifest(tmp_path)
    payload = manifest.model_dump(mode="json", by_alias=True)

    assert payload["$schema"] == "urn:a11y-devs:schema:processing-manifest:1.1.0"
    assert validate_manifest(payload) == []
    assert manifest.summary.page_count == 1
    assert [element.type for element in manifest.elements] == [
        "paragraph",
        "table",
        "picture",
        "paragraph",
        "formula",
    ]
    describe = [o for o in manifest.obligations if o.kind == "describe-image"]
    assert describe and describe[0].selected is False
    # The source is this file, not whatever the Toolbox recorded.
    assert manifest.source.filename == "sample.pdf"


def _build_from_response(tmp_path: Path, response: dict):
    timestamp = datetime(2026, 7, 27, tzinfo=timezone.utc)
    extraction = ToolboxExtraction(
        document=response,
        started_at=timestamp,
        completed_at=timestamp,
        duration_ms=5,
        version="toolbox-test",
        configuration={},
    )
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    return build_processing_manifest(source, extraction)


def test_obligations_come_from_the_core_policy_not_the_payload(tmp_path: Path):
    response = json.loads(TOOLBOX_RESPONSE.read_text(encoding="utf-8"))
    response["document"]["obligations"] = [{"id": "foreign", "kind": "toolbox-only"}]

    manifest = _build_from_response(tmp_path, response)

    assert all(o.kind != "toolbox-only" for o in manifest.obligations)


def test_callout_metadata_from_the_toolbox_passes_through(tmp_path: Path):
    # The PDDL orchestrator turns these fields into note/warning blocks.
    callout = {
        "callout_id": "callout-1",
        "callout_role": "body",
        "callout_type": "warning",
        "callout_title": "Atenção",
    }
    response = json.loads(TOOLBOX_RESPONSE.read_text(encoding="utf-8"))
    element = next(
        e for e in response["document"]["elements"] if e["id"] == "element-000004"
    )
    element["metadata"].update(callout)

    manifest = _build_from_response(tmp_path, response)

    built = next(e for e in manifest.elements if e.id == "element-000004")
    assert {key: built.metadata.get(key) for key in callout} == callout


def test_generated_schema_is_draft_2020_12():
    schema = processing_manifest_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "urn:a11y-devs:schema:processing-manifest:1.1.0"
    assert schema["title"] == "ProcessingManifest"
    schema_on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema_on_disk == schema


def test_manifest_rejects_unknown_target(tmp_path: Path):
    payload = _manifest(tmp_path).model_dump(mode="json", by_alias=True)
    payload["obligations"][0]["target_ids"] = ["element-inexistente"]

    errors = validate_manifest(payload)

    assert any("alvos inexistentes" in error for error in errors)


def test_a_non_toolbox_extraction_is_refused(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    extraction = SimpleNamespace(document=object(), configuration={})

    with pytest.raises(TypeError, match="Toolbox JSON extraction"):
        build_processing_manifest(source, extraction)


def test_an_extraction_without_a_document_is_refused(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")

    with pytest.raises(TypeError, match="Toolbox JSON extraction"):
        build_processing_manifest(source, SimpleNamespace(configuration={}))
