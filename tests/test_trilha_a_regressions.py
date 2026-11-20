"""Release 0.2.0 regressions from Trilha A; no external inference required."""

import asyncio
import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from tests.core_config_support import core_config, paths_config, toolbox_config
import pytest

from tests.core_config_support import fusion_config
from backend.config.settings import settings
from acessilia_core.pipeline.handlers import fusion as fusion_handlers
from acessilia_core.cache_keys import options_cache_key
from backend.services.cache import processing_cache_configuration
from tests.test_pending_fixes import isolated_runtime as isolated_runtime_fixture

isolated_runtime = isolated_runtime_fixture


@pytest.mark.parametrize(
    "name,value",
    [
        ("fusion_apply_page_routes", False),
        ("fusion_judge_max_pages", 999),
        ("processing_model_revision", "deployment-2"),
    ],
)
def test_cache_tracks_fusion_and_model_revision(monkeypatch, name, value):
    before = options_cache_key("document", config=processing_cache_configuration(core_config()))
    monkeypatch.setattr(settings, name, value, raising=False)
    assert (
        options_cache_key("document", config=processing_cache_configuration(core_config())) != before
    )


@pytest.mark.parametrize("extension", [".bmp", ".gif", ".webp"])
def test_unsupported_inputs_rejected_before_job_creation(extension):
    from backend.services.validators import validate_file

    assert validate_file("input" + extension, 100)[0] is False


@pytest.mark.asyncio
async def test_concurrent_downloads_have_independent_temporary_files(tmp_path):
    from acessilia_sdk.toolbox.artifacts import ArtifactRef, download_artifact

    arrived = 0
    ready = asyncio.Event()
    payload = b"%PDF-concurrent"
    ref = ArtifactRef.parse(hashlib.sha256(payload).hexdigest())

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal arrived
            yield payload[:5]
            arrived += 1
            if arrived == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 2)
            yield payload[5:]

    async with httpx.AsyncClient(
        base_url="http://toolbox",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=Stream())
        ),
    ) as client:
        await asyncio.gather(
            *(download_artifact(client, ref, tmp_path / "out.pdf") for _ in range(2))
        )
    assert (tmp_path / "out.pdf").read_bytes() == payload
    assert list(tmp_path.iterdir()) == [tmp_path / "out.pdf"]


@pytest.mark.parametrize("kind", ["table", "picture", "formula"])
def test_empty_structural_elements_contribute_to_fusion_evidence(kind):
    from docstruct.fusion.payload import group_payload_by_page as _group_by_page
    from acessilia_core.pipeline.fusion import fuse_extraction_payloads

    primary = {"document": {"elements": []}}
    secondary = {
        "document": {"elements": [{"type": kind, "text": "", "bbox": [0, 0, 1, 1]}]}
    }
    assert _group_by_page(secondary)[0][0]["type"] == kind
    result = fuse_extraction_payloads(
        primary, secondary, primary_provider="docling", secondary_provider="mineru"
    )
    stats = result["fusion_evidence"]["pages"][0]["stats"]
    assert stats["provider_divergence"] is True
    assert stats["text_divergence"] is False
    assert stats["structure_divergence"] is True
    if kind == "table":
        assert stats["table_divergence"] is True


def test_secondary_failure_reaches_result_configuration(monkeypatch, tmp_path):
    from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
    from acessilia_core.toolbox.toolbox_client import ToolboxProviderUnavailable
    from tests.test_toolbox_manifest_extractor import SAMPLE_TOOLBOX_RESPONSE

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    primary = SimpleNamespace(
        provider="docling",
        base_url="http://toolbox",
        extract_structure=AsyncMock(return_value=deepcopy(SAMPLE_TOOLBOX_RESPONSE)),
    )
    secondary = SimpleNamespace(
        extract_structure=AsyncMock(side_effect=ToolboxProviderUnavailable("offline")),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "acessilia_core.manifest.toolbox_extractor.make_toolbox_client",
        lambda *a, **k: secondary,
    )
    result = ToolboxManifestExtractor(client=primary).extract(
        source,
        fusion=fusion_config(mode="dual"),
        toolbox=toolbox_config(use_artifact_store=False),
        paths=paths_config(), operations=None
    )
    assert result.configuration["fusion"]["status"] == "degraded"
    assert result.configuration["fusion"]["failed_providers"] == ["mineru"]


def test_identical_providers_are_skipped_without_disabling_cache(monkeypatch, tmp_path):
    from acessilia_core.pipeline.payload import build_pddl_structured_payload
    from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
    from tests.test_pddl_orchestrator import _sample_manifest, _sample_plan
    from tests.test_toolbox_manifest_extractor import SAMPLE_TOOLBOX_RESPONSE

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    primary = SimpleNamespace(
        provider="docling",
        base_url="http://toolbox",
        extract_structure=AsyncMock(return_value=deepcopy(SAMPLE_TOOLBOX_RESPONSE)),
    )

    extracted = ToolboxManifestExtractor(client=primary).extract(
        source,
        fusion=fusion_config(mode="dual", secondary_provider="docling"),
        toolbox=toolbox_config(use_artifact_store=False),
        paths=paths_config(), operations=None
    )

    assert extracted.configuration["fusion"]["status"] == "skipped"
    assert extracted.configuration["fusion"]["reason"] == "identical-providers"
    manifest = _sample_manifest()
    manifest.obligations = []
    manifest.extractor.configuration["fusion"] = extracted.configuration["fusion"]
    result = build_pddl_structured_payload(
        file_path=source,
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=SimpleNamespace(status="completed", execution_id="test"),
        comparison=None,
    )
    assert result["cacheable"] is True


@pytest.mark.parametrize(
    "status,open_kind,last_method,expected",
    [
        ("completed", None, None, True),
        ("failed", None, None, False),
        ("replan-required", None, None, False),
        ("completed", "normalize-text", None, False),
        ("completed", "normalize-text", "human-review", True),
        ("completed", "recover-formula", "human-review", False),
    ],
)
def test_pddl_cache_policy(status, open_kind, last_method, expected):
    from acessilia_core.pipeline.payload import build_pddl_structured_payload
    from acessilia_core.manifest.models import Obligation, ObligationAttempt
    from tests.test_pddl_orchestrator import _sample_manifest, _sample_plan

    manifest = _sample_manifest()
    manifest.obligations = []
    if open_kind:
        obligation = Obligation(
            id="pending",
            kind=open_kind,
            target_ids=[manifest.elements[0].id],
            admissible_methods=["human-review"],
            method_costs={"human-review": 1},
            rationale="test",
            selected=True,
        )
        if last_method:
            obligation.attempts = [
                ObligationAttempt(
                    method=last_method,
                    status="failed",
                    started_at=manifest.created_at,
                    completed_at=manifest.created_at,
                    message="review",
                )
            ]
        manifest.obligations = [obligation]
    report = SimpleNamespace(status=status, execution_id="test")
    result = build_pddl_structured_payload(
        file_path=Path("doc.pdf"),
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=report,
        comparison=None,
    )
    assert result["cacheable"] is expected
    manifest.extractor.configuration["fusion"] = {
        "status": "degraded",
        "failed_providers": ["mineru"],
    }
    result = build_pddl_structured_payload(
        file_path=Path("doc.pdf"),
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=report,
        comparison=None,
    )
    assert result["cacheable"] is False
    assert result["canonical_metadata"]["pddl_fusion"]["status"] == "degraded"


def _reuse_identity():
    from acessilia_core.run_identity import fusion_reuse_identity

    config = core_config()
    return fusion_reuse_identity(config.fusion, config.toolbox)


@pytest.mark.parametrize("corrupt", [False, True, "configuration"])
def test_dual_fusion_reuses_verified_inputs(tmp_path, monkeypatch, corrupt):
    import json
    from acessilia_core.manifest.toolbox_extractor import _persist_fusion_reuse
    from tests.test_dual_provider_fusion import _dual_payload, _make_manifest

    manifest = _make_manifest(tmp_path)
    source = Path(manifest.source.path)
    source.write_bytes(b"%PDF-fusion-reuse")
    manifest.source.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    payload = _dual_payload()
    ref = _persist_fusion_reuse(source, payload, None, data_dir=paths_config().data_dir, identity=_reuse_identity())
    manifest.extractor.configuration["fusion_reuse"] = ref
    path = Path(ref["path"])
    record = json.loads(path.read_bytes())
    assert set(record) == {"source_sha256", "identity", "policy", "payload"}
    assert record["payload"] == payload
    if corrupt is True:
        path.write_text("tampered")
    calls = []

    def extract(*a, **k):
        calls.append(True)
        return payload

    monkeypatch.setattr(fusion_handlers, "_run_extract_fused", extract)
    # A run whose fusion options differ from the stored record's (#544).
    run = core_config(fusion={"judge_max_pages": 998}) if corrupt == "configuration" else core_config()
    result = fusion_handlers._handle_dual_provider_fusion_method(manifest, "o-fuse", config=run)
    assert result.success
    assert calls == ([True] if corrupt else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("healthy", [True, False])
async def test_core_readiness_follows_toolbox(monkeypatch, healthy):
    from backend.api.routes import health

    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "provider": request.url.path.rsplit("/", 2)[-2],
                "healthy": healthy,
                "checked_at": "2026-10-28T00:00:00Z",
            },
        )

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(health.settings, "toolbox_base_urls", "")
    monkeypatch.setattr(health.settings, "toolbox_base_url", "http://toolbox.test")
    monkeypatch.setattr(health.settings, "toolbox_provider", "docling")
    monkeypatch.setattr(health.settings, "fusion_mode", "single")
    monkeypatch.setattr(health.settings, "toolbox_api_key", "test-key")
    monkeypatch.setattr(
        health.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw)
    )
    response = await health.ready()
    assert response.status_code == (200 if healthy else 503)
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/providers/docling/health"
    assert requests[0].headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,kind,human_review,expected_calls",
    [
        ("completed", None, False, 1),
        ("failed", None, False, 2),
        ("replan-required", None, False, 2),
        ("completed", "normalize-text", False, 2),
        ("completed", "normalize-text", True, 1),
        ("completed", "recover-formula", True, 2),
    ],
)
async def test_pddl_recovery_policy_controls_real_cache_replay(
    isolated_runtime, monkeypatch, tmp_path, status, kind, human_review, expected_calls
):
    """A second submission retries technical failures and reuses final results."""
    from backend import service
    from acessilia_core.pipeline.payload import build_pddl_structured_payload
    from acessilia_core.manifest.models import Obligation, ObligationAttempt
    from backend.services import cache
    from tests.test_pddl_orchestrator import _sample_manifest, _sample_plan

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(service, "_salvar_json_canonico", lambda *args: None)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF-cache-recovery-contract")

    class Agent:
        calls = 0

        async def execute(self, file_path, *args, **kwargs):
            self.calls += 1
            manifest = _sample_manifest()
            manifest.obligations = []
            if kind and self.calls == 1:
                obligation = Obligation(
                    id="pending",
                    kind=kind,
                    target_ids=[manifest.elements[0].id],
                    admissible_methods=["human-review"],
                    method_costs={"human-review": 1},
                    selected=True,
                    rationale="Cache integration contract",
                )
                if human_review:
                    obligation.attempts = [
                        ObligationAttempt(
                            method="human-review",
                            status="failed",
                            started_at=manifest.created_at,
                            completed_at=manifest.created_at,
                        )
                    ]
                manifest.obligations = [obligation]
            return build_pddl_structured_payload(
                file_path=file_path,
                manifest=manifest,
                plan=_sample_plan(),
                planner_backend="internal",
                execution_report=SimpleNamespace(
                    status=status if self.calls == 1 else "completed",
                    execution_id=f"execution-{self.calls}",
                ),
                comparison=None,
            )

    agent = Agent()
    monkeypatch.setattr(service, "agente", agent)
    await service.process(source, task_id="first-submission", config=core_config())
    assert len(list(cache.CACHE_DIR.glob("*.json"))) == (expected_calls == 1)
    await service.process(source, task_id="second-submission", config=core_config())
    await service.process(source, task_id="third-submission", config=core_config())
    assert agent.calls == expected_calls
    assert len(list(cache.CACHE_DIR.glob("*.json"))) == 1

@pytest.mark.parametrize('kind', ['table', 'picture', 'formula'])
def test_route_uses_structure_when_text_agrees(kind):
    from acessilia_core.pipeline.fusion import fuse_extraction_payloads

    text = {'type': 'paragraph', 'text': 'Texto da pagina com conteudo suficiente', 'page': 0}
    primary = {'document': {'elements': [text]}}
    secondary = {'document': {'elements': [text, {'type': kind, 'text': '', 'page': 0, 'bbox': [0, 0, 1, 1]}]}}
    result = fuse_extraction_payloads(primary, secondary, primary_provider='docling', secondary_provider='mineru')
    stats = result['fusion_evidence']['pages'][0]['stats']
    assert stats['route'] == 'mineru'
    assert stats['route_reason'] == 'secondary_structure_superset'


def test_reuse_accepts_effective_custom_policy(tmp_path, monkeypatch):
    from dataclasses import asdict

    from docstruct.policy import FusionPolicy

    from acessilia_core.manifest.toolbox_extractor import _persist_fusion_reuse
    from tests.test_dual_provider_fusion import _dual_payload, _make_manifest

    manifest = _make_manifest(tmp_path)
    source = Path(manifest.source.path)
    source.write_bytes(b'%PDF-policy')
    manifest.source.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    policy = FusionPolicy(align_tau=0.4)
    payload = _dual_payload()
    manifest.extractor.configuration['fusion_reuse'] = _persist_fusion_reuse(source, payload, policy, data_dir=paths_config().data_dir, identity=_reuse_identity())
    manifest.extractor.configuration['fusion_policy'] = asdict(policy)
    assert fusion_handlers._reusable_fusion_payload(manifest, core_config()) == payload
    manifest.extractor.configuration['fusion_policy'] = asdict(FusionPolicy(align_tau=0.8))
    assert fusion_handlers._reusable_fusion_payload(manifest, core_config()) is None


def test_reextract_uses_effective_custom_policy(tmp_path, monkeypatch):
    from dataclasses import asdict

    from docstruct.policy import FusionPolicy

    from tests.test_dual_provider_fusion import _dual_payload, _make_manifest

    manifest = _make_manifest(tmp_path)
    policy = FusionPolicy(align_tau=0.4)
    manifest.extractor.configuration['fusion_policy'] = asdict(policy)
    seen = []
    def extract(path, *, artifact_id=None, policy=None, secondary_provider=None, toolbox=None):
        seen.append(policy)
        return _dual_payload()
    monkeypatch.setattr(fusion_handlers, '_run_extract_fused', extract)
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    assert fusion_handlers._handle_dual_provider_fusion_method(manifest, 'o-fuse', config=core_config()).success
    assert seen == [policy]


def test_handler_reuses_matching_policy_and_reextracts_with_changed_policy(tmp_path, monkeypatch):
    from dataclasses import asdict

    from docstruct.policy import FusionPolicy

    from acessilia_core.manifest.toolbox_extractor import _persist_fusion_reuse
    from tests.test_dual_provider_fusion import _dual_payload, _make_manifest

    manifest = _make_manifest(tmp_path)
    source = Path(manifest.source.path)
    source.write_bytes(b'%PDF-policy-integration')
    manifest.source.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    original = FusionPolicy(align_tau=0.4)
    changed = FusionPolicy(align_tau=0.8)
    payload = _dual_payload()
    manifest.extractor.configuration['fusion_reuse'] = _persist_fusion_reuse(source, payload, original, data_dir=paths_config().data_dir, identity=_reuse_identity())
    manifest.extractor.configuration['fusion_policy'] = asdict(original)
    calls = []
    def extract(path, *, artifact_id=None, policy=None, secondary_provider=None, toolbox=None):
        calls.append(policy)
        return payload
    monkeypatch.setattr(fusion_handlers, '_run_extract_fused', extract)
    assert fusion_handlers._handle_dual_provider_fusion_method(manifest, 'o-fuse', config=core_config()).success
    assert not calls
    manifest.extractor.configuration['fusion_policy'] = asdict(changed)
    assert fusion_handlers._handle_dual_provider_fusion_method(manifest, 'o-fuse', config=core_config()).success
    assert calls == [changed]
