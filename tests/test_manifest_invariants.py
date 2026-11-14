"""The document invariants agree between docstruct and the core runtime model (#404).

Each accepted rule is exercised through both docstruct APIs and through
``ProcessingManifest``, whose validator raises the first finding. The two
historical manifests also have to keep validating after the new rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.i18n import t
from backend.core.manifest.models import (
    MSG_ELEMENT_UNKNOWN_PAGE,
    MSG_PAGE_DUPLICATE_ELEMENT_IDS,
    MSG_PARENT_REF_MISMATCH,
    MSG_PROVENANCE_UNKNOWN_PAGE,
    ProcessingManifest,
)
from docstruct.manifest import (
    document_invariant_findings,
    structured_document_from_payload,
    validate_structured_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "manifests"


def _manifest_payload() -> dict:
    return json.loads((FIXTURES / "two-pages-refined.json").read_text("utf-8"))


def _document(payload: dict):
    return structured_document_from_payload(
        {
            key: payload[key]
            for key in ("title", "language", "pages", "elements")
        }
    )


def _new_element_page(payload: dict) -> None:
    payload["elements"][0]["page_number"] = 99


def _new_provenance_page(payload: dict) -> None:
    payload["elements"][0]["provenance"][0]["page_number"] = 99


def _duplicate_page_member(payload: dict) -> None:
    payload["pages"][0]["element_ids"].append(payload["pages"][0]["element_ids"][0])


def _mismatched_parent_ref(payload: dict) -> None:
    parent, child = payload["elements"][0], payload["elements"][1]
    parent["source_ref"] = "#/texts/0"
    child["parent_id"] = parent["id"]
    child["parent_ref"] = "#/texts/1"


CASES = [
    (_new_element_page, MSG_ELEMENT_UNKNOWN_PAGE),
    (_new_provenance_page, MSG_PROVENANCE_UNKNOWN_PAGE),
    (_duplicate_page_member, MSG_PAGE_DUPLICATE_ELEMENT_IDS),
    (_mismatched_parent_ref, MSG_PARENT_REF_MISMATCH),
]


@pytest.mark.parametrize(("mutate", "msgid"), CASES)
def test_each_rule_is_a_finding_in_docstruct_and_an_error_in_the_core(
    mutate, msgid
) -> None:
    payload = _manifest_payload()
    mutate(payload)
    document = _document(payload)

    findings = validate_structured_document(document)
    invariant_findings = document_invariant_findings(
        document.pages, document.elements
    )

    assert findings == invariant_findings
    assert [found[0] for found in findings] == [msgid]
    with pytest.raises(ValueError) as raised:
        ProcessingManifest.model_validate(payload)
    assert t(msgid).split("{")[0] in str(raised.value)


@pytest.mark.parametrize(
    "name", ["two-pages-refined.json", "toolbox-v2-contract.json"]
)
def test_historical_manifests_still_validate(name: str) -> None:
    payload = json.loads((FIXTURES / name).read_text("utf-8"))

    ProcessingManifest.model_validate(payload)
    assert validate_structured_document(_document(payload)) == []


def test_an_element_updates_on_another_page_when_pages_are_empty() -> None:
    """pages=[] is an element-only document: page numbers are trusted."""
    payload = _manifest_payload()
    payload["pages"] = []
    payload["summary"]["page_count"] = 0
    document = _document(payload)

    assert validate_structured_document(document) == []
    ProcessingManifest.model_validate(payload)


def test_an_element_may_be_listed_on_no_page() -> None:
    payload = _manifest_payload()
    payload["pages"][0]["element_ids"].remove(payload["elements"][0]["id"])

    assert validate_structured_document(_document(payload)) == []
    ProcessingManifest.model_validate(payload)


def test_the_cache_identity_includes_the_invariant_revision() -> None:
    """Old cached manifests are not reopened under the new rules."""
    from backend.services.cache import (
        MANIFEST_INVARIANT_REVISION,
        processing_cache_configuration,
    )

    configuration = processing_cache_configuration()

    assert (
        configuration["manifest_invariant_revision"]
        == MANIFEST_INVARIANT_REVISION
    )
