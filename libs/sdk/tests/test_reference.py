"""artifact/reference@1 in the SDK: the generated model, its reader and compatibility (#185).

The model (``acessilia_sdk.toolbox.reference``) is generated from the schema
the Toolbox publishes; ``parse_reference`` adds the rule the schema cannot
state (``digest == artifact_id``). The id-parsing helper ``ArtifactRef`` stays
for callers that only hold an id.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox import (
    ArtifactRef,
    ArtifactReference,
    ToolboxContractViolation,
    parse_reference,
)
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient
from acessilia_sdk.toolbox.reference import REQUIRED, SCHEMA_ID

BASE_URL = "http://localhost:8002"
FIXTURE_PDF = Path(__file__).parent / "clients" / "fixtures" / "sample.pdf"
CONTENT = FIXTURE_PDF.read_bytes()
HEX = hashlib.sha256(CONTENT).hexdigest()
ARTIFACT_ID = f"sha256:{HEX}"

#: What the Toolbox's POST /v1/artifacts answers since acessilia-toolbox#151.
REFERENCE = {
    "artifact_id": ARTIFACT_ID,
    "digest": ARTIFACT_ID,
    "media_type": "application/pdf",
    "size": len(CONTENT),
    "store": "s3",
}
#: What an earlier Toolbox answered: its stored record.
LEGACY_RECORD = {
    "artifact_id": ARTIFACT_ID,
    "media_type": "application/pdf",
    "size": len(CONTENT),
    "uri": "s3://acessilia/objects/xx",
    "storage_backend": "s3",
    "filename": "sample.pdf",
}


def test_the_model_is_the_published_schema() -> None:
    assert SCHEMA_ID == "urn:a11y-devs:schema:reference:1.0.0"
    assert REQUIRED == ("artifact_id", "digest", "media_type", "size", "store")


def test_a_reference_is_read_and_written_back_unchanged() -> None:
    reference = parse_reference(REFERENCE)

    assert reference == ArtifactReference(**REFERENCE)
    assert reference.to_dict() == REFERENCE


def test_a_reference_without_a_storage_location_is_read() -> None:
    assert parse_reference({**REFERENCE, "store": None}).store is None


def test_unknown_fields_are_ignored_so_a_later_version_is_still_read() -> None:
    """reference@2 adds scope and provenance; @1 readers keep working."""
    reference = parse_reference({**REFERENCE, "scope": {"tenant": "t"}, "provenance": {}})

    assert reference.to_dict() == REFERENCE


@pytest.mark.parametrize("field", REQUIRED)
def test_a_missing_field_is_refused_never_invented(field: str) -> None:
    document = {key: value for key, value in REFERENCE.items() if key != field}

    with pytest.raises(ToolboxContractViolation, match=field):
        parse_reference(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_id", HEX),  # the canonical form is required on the wire
        ("artifact_id", "sha256:XYZ"),
        ("digest", "md5:" + "ab" * 16),
        ("media_type", ""),
        ("size", "10"),
        ("size", True),
        ("size", -1),
        ("store", ""),
        ("store", 3),
    ],
)
def test_a_value_the_schema_refuses_is_refused(field: str, value: object) -> None:
    with pytest.raises(ToolboxContractViolation, match=field):
        parse_reference({**REFERENCE, field: value})


def test_a_digest_that_differs_from_the_id_is_refused() -> None:
    """Draft-07 accepts this document; the SDK checks the rule again (ADR-0015)."""
    other = "sha256:" + "cd" * 32

    with pytest.raises(ToolboxContractViolation, match="differs from artifact_id"):
        parse_reference({**REFERENCE, "digest": other})


@pytest.mark.parametrize("data", [None, [], "sha256:" + HEX])
def test_a_document_that_is_not_an_object_is_refused(data: object) -> None:
    with pytest.raises(ToolboxContractViolation):
        parse_reference(data)


def test_the_id_helper_reads_a_reference_id_and_a_bare_stored_id() -> None:
    """References already stored may hold a bare id; both parse to the same digest."""
    from_reference = ArtifactRef.parse(parse_reference(REFERENCE).artifact_id)
    from_bare = ArtifactRef.parse(HEX)

    assert from_reference.digest == from_bare.digest == HEX


# ── Compatibility between SDK and Toolbox versions ─────────────────────────


@pytest.fixture
def client() -> ToolboxArtifactClient:
    return ToolboxArtifactClient(base_url=BASE_URL, timeout_seconds=30)


@pytest.mark.asyncio
async def test_upload_reference_against_a_toolbox_with_reference_at_1(respx_mock, client):
    respx_mock.post(f"{BASE_URL}/v1/artifacts").mock(
        return_value=httpx.Response(200, json=REFERENCE)
    )

    assert await client.upload_reference(FIXTURE_PDF) == ArtifactReference(**REFERENCE)


@pytest.mark.asyncio
async def test_upload_reference_against_an_earlier_toolbox_says_so(respx_mock, client):
    """New SDK, old Toolbox: no digest or store is invented."""
    respx_mock.post(f"{BASE_URL}/v1/artifacts").mock(
        return_value=httpx.Response(200, json=LEGACY_RECORD)
    )

    with pytest.raises(ToolboxContractViolation, match="predates artifact/reference@1"):
        await client.upload_reference(FIXTURE_PDF)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [REFERENCE, LEGACY_RECORD], ids=["reference@1", "legacy"])
async def test_upload_returns_the_id_from_either_toolbox(respx_mock, client, answer):
    """upload() reads only the id, as the SDK did before this change."""
    respx_mock.post(f"{BASE_URL}/v1/artifacts").mock(
        return_value=httpx.Response(200, json=answer)
    )

    assert await client.upload(FIXTURE_PDF) == ARTIFACT_ID
