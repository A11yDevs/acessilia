"""Typed layout reuses docstruct and keeps raw compatibility helpers."""

import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from docstruct.manifest import BoundingBox, StructuredDocument
from acessilia_sdk.toolbox.clients.layout import ToolboxLayoutClient
from acessilia_sdk.toolbox.clients.structure import ToolboxStructureClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation, ToolboxTimeout
from acessilia_sdk.toolbox.results.layout import read_layout, read_manifest

FIXTURES = Path(__file__).parent / "fixtures"


def example(variant):
    return json.loads((FIXTURES / f"{variant}-layout.json").read_text())


@pytest.mark.parametrize("variant", ["docling", "mineru"])
def test_both_layout_variants_and_extensions(variant):
    document = example(variant)
    if variant == "docling":
        document["future_metadata"] = {"a": 1}
    else:
        document["extractor"]["configuration"]["layout_regions"][0]["bbox"][
            "future"
        ] = True
    layout = read_layout(document)
    assert layout.variant == variant
    assert isinstance(layout.regions[0].bbox, BoundingBox)
    assert layout.regions[0].bbox.coord_origin == (
        "TOPLEFT" if variant == "docling" else "UNKNOWN"
    )
    if variant == "docling":
        assert layout.compact.to_dict() == document
        assert layout.regions[0].page_number == 2
        assert layout.regions[0].confidence == 0.95
    else:
        assert isinstance(layout.manifest.document, StructuredDocument)
        assert layout.manifest.to_dict() == document
        assert layout.configuration.layout_regions[0].page == 0
        assert layout.regions[0].page_number == 1
        assert layout.regions[0].confidence is None
        assert layout.manifest.producer["source"] == document["source"]
        assert "elements" not in layout.manifest.producer


def test_canonical_origin_is_not_invented():
    document = example("mineru")
    box = document["elements"][0]["provenance"][0]["bbox"]
    box["coord_origin"] = "UNKNOWN"
    document["pages"][0]["width"] = None
    layout = read_layout(document)
    assert (
        layout.manifest.document.elements[0].provenance[0].bbox.coord_origin
        == "UNKNOWN"
    )
    assert layout.manifest.document.pages[0].width is None
    assert layout.regions[0].bbox.coord_origin == "UNKNOWN"


@pytest.mark.parametrize("variant", ["docling", "mineru"])
def test_empty_results(variant):
    document = example(variant)
    if variant == "docling":
        document = {"pages": [], "page_count": 0, "region_count": 0}
    else:
        document["extractor"]["configuration"].update(layout_regions=[], region_count=0)
        document["elements"] = []
        for page in document["pages"]:
            page["element_ids"] = []
        document["observations"] = []
        document["obligations"] = []
        document["summary"].update(
            element_count=0, observation_count=0, obligation_count=0, element_types={}
        )
    assert read_layout(document).regions == ()


@pytest.mark.parametrize(
    "field", ["configuration", "backend", "region_count", "layout_regions"]
)
def test_generic_manifest_is_not_a_layout_result(field):
    document = example("mineru")
    if field == "configuration":
        del document["extractor"][field]
    else:
        del document["extractor"]["configuration"][field]
    # The source remains a valid structural extraction, but not a layout.
    assert isinstance(read_manifest(document).document, StructuredDocument)
    with pytest.raises(ToolboxContractViolation):
        read_layout(document)


@pytest.mark.asyncio
async def test_typed_accessors_and_legacy_page_maps():
    layout = ToolboxLayoutClient(base_url="http://toolbox")
    structure = ToolboxStructureClient(base_url="http://toolbox")
    try:
        document = example("mineru")
        layout.analyze = AsyncMock(return_value={"document": document})
        assert (await layout.analyze_result()).variant == "mineru"
        structure.extract_structure = AsyncMock(return_value={"document": document})
        assert isinstance(
            (await structure.extract_structure_result()).document, StructuredDocument
        )
        layout.analyze.return_value = {
            "document": {"pages": {"1": {"page_number": 1, "regions": []}}}
        }
        assert await layout.analyze_pages() == [{"page_number": 1, "regions": []}]
        with pytest.raises(ToolboxContractViolation):
            await layout.analyze_result()
        layout.analyze.side_effect = ToolboxTimeout("slow")
        with pytest.raises(ToolboxTimeout):
            await layout.analyze_result()
    finally:
        await layout.close()
        await structure.close()


@pytest.mark.parametrize("reader", [read_manifest, read_layout])
@pytest.mark.parametrize(
    "issue, message",
    [
        ("duplicate", "Duplicate element ids"),
        ("parent", "missing parent: missing-parent"),
        ("page", "references missing page 999"),
        ("provenance", "references missing page 999"),
    ],
)
def test_canonical_readers_reject_invalid_document_references(reader, issue, message):
    document = example("mineru")
    if issue == "duplicate":
        document["elements"][1]["id"] = document["elements"][0]["id"]
    elif issue == "parent":
        document["elements"][0]["parent_id"] = "missing-parent"
    elif issue == "page":
        document["elements"][0]["page_number"] = 999
    else:
        document["elements"][0]["provenance"][0]["page_number"] = 999
    original = copy.deepcopy(document)
    with pytest.raises(ToolboxContractViolation, match=message):
        reader(document)
    assert document == original


@pytest.mark.parametrize("kind", ["layout", "structure"])
@pytest.mark.asyncio
async def test_typed_accessors_propagate_canonical_validation_errors(kind):
    document = example("mineru")
    document["elements"][0]["parent_id"] = "missing-parent"
    response = {"document": document}
    if kind == "layout":
        client = ToolboxLayoutClient(base_url="http://toolbox")
        raw, typed = client.analyze, client.analyze_result
    else:
        client = ToolboxStructureClient(base_url="http://toolbox")
        raw, typed = client.extract_structure, client.extract_structure_result
    try:
        client._execute = AsyncMock(return_value=response)
        assert await raw() == response
        with pytest.raises(ToolboxContractViolation, match="missing parent"):
            await typed()
        assert await raw() == response
    finally:
        await client.close()


def test_valid_element_only_fragments_keep_docstruct_page_reference_policy():
    document = example("mineru")
    document["pages"] = []
    document["summary"]["page_count"] = 0
    for result in (read_manifest(document), read_layout(document).manifest):
        assert result.document.pages == []
        assert result.document.elements[0].page_number == 1
        assert result.to_dict() == document


# --- docstruct's shared contract cases (#470, criterion 4) -------------------
#
# The core and the Toolbox run the same catalog against their own models; the
# SDK's reader must agree with docstruct on each case. They go into docstruct's
# example document, which has references and a child, inside the fixture's
# producer fields. The fixture's observations and obligations target its own
# elements, so the manifest goes without them, and stays a valid one for the
# Toolbox's model too (review of #593).

from docstruct.manifest import (  # noqa: E402
    MSG_FIELD_NOT_ALLOWED,
    MSG_FIELD_OUT_OF_RANGE,
    MSG_FIELD_WRONG_TYPE,
)
from docstruct.manifest_cases import (  # noqa: E402
    BROKEN,
    SUPPORTED,
    document_findings,
    example_document,
)


def _shared_case_manifest(change):
    document = example("mineru")
    document.update(example_document(), observations=[], obligations=[])
    change(document)
    types = {}
    for element in document["elements"]:
        types[element["type"]] = types.get(element["type"], 0) + 1
    document["summary"].update(
        page_count=len(document["pages"]),
        element_count=len(document["elements"]),
        observation_count=0,
        obligation_count=0,
        element_types=dict(sorted(types.items())),
    )
    return document


def test_the_shared_example_is_a_valid_toolbox_manifest():
    document = _shared_case_manifest(lambda payload: None)
    assert read_manifest(document).to_dict() == document


@pytest.mark.parametrize("case", list(BROKEN))
def test_the_reader_and_docstruct_reject_the_same_documents(case):
    """For the same reason, not only both (review of #591): a field finding at
    the same path, an unknown field as unknown properties, and an invariant
    with docstruct's message."""
    document = _shared_case_manifest(BROKEN[case])
    findings = document_findings(document)
    assert findings != []
    message, context = findings[0]

    with pytest.raises(ToolboxContractViolation) as raised:
        read_manifest(document)

    reported = str(raised.value)
    if message == "refused":
        assert "unknown properties" in reported
    elif message in (MSG_FIELD_WRONG_TYPE, MSG_FIELD_OUT_OF_RANGE, MSG_FIELD_NOT_ALLOWED):
        assert f"ProcessingManifest.{context['path']}:" in reported
    else:
        assert message.format(**context) in reported


@pytest.mark.parametrize("case", list(SUPPORTED))
def test_the_reader_and_docstruct_keep_the_same_documents(case):
    document = _shared_case_manifest(SUPPORTED[case])
    assert document_findings(document) == []
    assert read_manifest(document).to_dict() == document
