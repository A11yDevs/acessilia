"""B07 characterization through the real core orchestrator and SDK HTTP clients."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from acessilia_sdk.toolbox import ToolboxArtifactNotFound
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient, ToolboxStructureClient

from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor

A = "http://toolbox-a.test"
B = "http://toolbox-b.test"
CAPABILITY = "document.structure.extract"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shared_store", [False, True], ids=["independent-storage", "shared-storage"]
)
@pytest.mark.parametrize(
    "upload_fails_on_a", [False, True], ids=["extraction-failover", "upload-failover"]
)
async def test_upload_and_extraction_choose_endpoints_independently(
    tmp_path: Path, shared_store: bool, upload_fails_on_a: bool
) -> None:
    source = tmp_path / "b07.pdf"
    payload = b"%PDF-B07 simulated document"
    source.write_bytes(payload)
    artifact_id = "sha256:" + hashlib.sha256(payload).hexdigest()
    stored_a: set[str] = set()
    stored_b = stored_a if shared_store else set()
    events: list[tuple[str, str]] = []

    def upload(base: str, stored: set[str], fail: bool):
        def respond(request: httpx.Request) -> httpx.Response:
            events.append((base, "upload"))
            if fail:
                return httpx.Response(503, json={"code": "provider_unavailable"})
            assert payload in request.content
            stored.add(artifact_id)
            return httpx.Response(200, json={"artifact_id": artifact_id})

        return respond

    def extract(base: str, stored: set[str], fail: bool):
        def respond(request: httpx.Request) -> httpx.Response:
            events.append((base, "extract"))
            assert parse_qs(request.content.decode())["artifact_id"] == [artifact_id]
            assert "multipart/form-data" not in request.headers.get("content-type", "")
            if fail:
                return httpx.Response(503, json={"code": "provider_unavailable"})
            if artifact_id not in stored:
                return httpx.Response(404, json={"code": "artifact_not_found"})
            return httpx.Response(
                200,
                json={
                    "status": "succeeded",
                    "provider": "docling",
                    "document": {"pages": [], "elements": []},
                    "provenance": {"provider_version": "test"},
                },
            )

        return respond

    artifacts = ToolboxArtifactClient(endpoints=[A, B], retries=0)
    structure = ToolboxStructureClient(endpoints=[A, B], provider="docling", retries=0)
    try:
        with respx.mock(assert_all_called=False) as router:
            router.get(B + "/v1/capabilities").respond(
                200,
                json=[
                    {"id": "artifact.store", "version": 1},
                    {"id": CAPABILITY, "version": 1},
                ],
            )
            router.get(B + "/v1/providers").respond(
                200,
                json=[
                    {"id": "minio", "capabilities": ["artifact.store"]},
                    {"id": "docling", "capabilities": [CAPABILITY]},
                ],
            )
            router.post(A + "/v1/artifacts").mock(
                side_effect=upload(A, stored_a, upload_fails_on_a)
            )
            upload_b = router.post(B + "/v1/artifacts").mock(
                side_effect=upload(B, stored_b, False)
            )
            execute_a = router.post(A + f"/v1/capabilities/{CAPABILITY}:execute").mock(
                side_effect=extract(A, stored_a, not upload_fails_on_a)
            )
            execute_b = router.post(B + f"/v1/capabilities/{CAPABILITY}:execute").mock(
                side_effect=extract(B, stored_b, False)
            )
            uploaded_id = await artifacts.upload(source)
            assert uploaded_id == artifact_id
            if shared_store:
                result = await structure.extract_structure(artifact_id=uploaded_id)
                assert result["status"] == "succeeded"
            else:
                with pytest.raises(ToolboxArtifactNotFound):
                    await structure.extract_structure(artifact_id=uploaded_id)

            assert execute_a.call_count == 1
            assert execute_b.call_count == (0 if upload_fails_on_a else 1)
            assert upload_b.call_count == (1 if upload_fails_on_a else 0)
            assert events == (
                [(A, "upload"), (B, "upload"), (A, "extract")]
                if upload_fails_on_a
                else [(A, "upload"), (A, "extract"), (B, "extract")]
            )
    finally:
        await artifacts.close()
        await structure.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_unavailable", [False, True])
@pytest.mark.parametrize("use_artifact_store", [False, True])
async def test_direct_file_extraction_does_not_require_shared_artifact_storage(
    tmp_path: Path, primary_unavailable: bool, use_artifact_store: bool
) -> None:
    source = tmp_path / "b07.pdf"
    payload = b"%PDF-B07 direct extraction"
    source.write_bytes(payload)
    artifacts = ToolboxArtifactClient(endpoints=[A, B], retries=0)
    structure = ToolboxStructureClient(endpoints=[A, B], provider="docling", retries=0)
    extractor = ToolboxManifestExtractor(
        client=structure,
        artifact_client=artifacts,
        use_artifact_store=use_artifact_store,
    )

    def extract(request: httpx.Request) -> httpx.Response:
        assert payload in request.content
        assert b'filename="b07.pdf"' in request.content
        assert b'name="artifact_id"' not in request.content
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "provider": "docling",
                "document": {"pages": [], "elements": []},
            },
        )

    try:
        with respx.mock(assert_all_called=False) as router:
            upload_a = router.post(A + "/v1/artifacts")
            upload_b = router.post(B + "/v1/artifacts")
            router.get(B + "/v1/capabilities").respond(
                200,
                json=[
                    {"id": CAPABILITY, "version": 1},
                ],
            )
            router.get(B + "/v1/providers").respond(
                200,
                json=[
                    {"id": "docling", "capabilities": [CAPABILITY]},
                ],
            )
            execute_a = router.post(A + f"/v1/capabilities/{CAPABILITY}:execute")
            if primary_unavailable:
                execute_a.respond(503, json={"code": "provider_unavailable"})
            else:
                execute_a.mock(side_effect=extract)
            execute_b = router.post(B + f"/v1/capabilities/{CAPABILITY}:execute").mock(
                side_effect=extract
            )
            result = await extractor._extract_with(
                structure, artifacts, source, dual_fusion=False
            )
            assert result.document["status"] == "succeeded"
            assert result.artifact_id is None
            assert not upload_a.called and not upload_b.called
            assert execute_a.call_count == 1
            assert execute_b.call_count == int(primary_unavailable)
    finally:
        await artifacts.close()
        await structure.close()
