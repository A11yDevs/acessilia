"""Smoke the pinned external benchmark adapter against this Core checkout."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["structure", "pipeline"])
@pytest.mark.external_adapter
def test_external_adapter_uses_current_core_interfaces(tmp_path, engine):
    adapter_path = os.environ.get("ACESSILIA_BENCHMARK_ADAPTER")
    if not adapter_path:
        pytest.skip("set ACESSILIA_BENCHMARK_ADAPTER to run the external adapter smoke test")
    adapter = Path(adapter_path)
    assert adapter.is_file(), f"external benchmark adapter not found: {adapter}"

    core_root = Path(__file__).resolve().parents[1]
    image = tmp_path / "page.png"
    image.write_bytes(b"offline benchmark adapter fixture")
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"id": "smoke-page", "images": [str(image)]}), encoding="utf-8"
    )
    output = tmp_path / "prediction.md"

    harness = r"""
import importlib.util
import json
import os
import sys
from pathlib import Path

engine = os.environ["SMOKE_ENGINE"]
if engine == "pipeline":
    os.environ["PIPELINE_ENGINE"] = "pddl"
    os.environ["PDDL_EXECUTE_DRY_RUN"] = "false"

core = Path(os.environ["SMOKE_CORE_ROOT"]).resolve()
sys.path[:0] = [
    str(core),
    str(core / "libs/docstruct/src"),
    str(core / "libs/sdk/src"),
]

calls = []

if engine == "structure":
    import acessilia_sdk.toolbox.clients as sdk_clients
    import backend.core.toolbox.toolbox_client as core_toolbox
    from backend.core.config import ToolboxConfig

    class SmokeClient:
        async def extract_structure(self, *, file_path, use_remote_cache):
            assert Path(file_path).is_file()
            assert isinstance(use_remote_cache, bool)
            calls.append(("extract", use_remote_cache))
            return {
                "document": {
                    "elements": [{"type": "paragraph", "text": "Adapter smoke page"}]
                },
                "provenance": {
                    "capability": "document.structure.extract",
                    "provider": "docling",
                    "cache_hit": False,
                    "duration_ms": 1,
                },
            }

        async def close(self):
            calls.append(("close",))

    def smoke_factory(client_class, toolbox, **overrides):
        assert client_class is SmokeClient
        assert isinstance(toolbox, ToolboxConfig)
        assert overrides == {"provider": "docling"}
        calls.append(("factory", overrides["provider"]))
        return SmokeClient()

    sdk_clients.ToolboxStructureClient = SmokeClient
    core_toolbox.make_toolbox_client = smoke_factory
else:
    import inspect
    import backend.service as core_service
    from backend.core.config import CoreConfig

    assert inspect.signature(core_service.process).parameters["config"].default is None
    assert isinstance(core_service._resolve_process_config(None), CoreConfig)

    async def smoke_process(
        file_path, status_callback=None, mode="normal", custom_prompt=None,
        thinking_mode=False, task_id=None, display_filename=None, resumed=False, *, config=None
    ):
        assert Path(file_path).is_file()
        assert mode == "normal"
        assert isinstance(core_service._resolve_process_config(config), CoreConfig)
        calls.append(("pipeline", mode))
        return {
            "title": "Adapter smoke page",
            "sections": [{
                "level": 1,
                "title": "",
                "blocks": [{"type": "paragraph", "text": "Adapter smoke page"}],
            }],
        }

    core_service.process = smoke_process

adapter_path = Path(os.environ["ACESSILIA_BENCHMARK_ADAPTER"]).resolve()
spec = importlib.util.spec_from_file_location("external_acessilia_adapter", adapter_path)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

request = Path(os.environ["SMOKE_REQUEST"])
output = Path(os.environ["SMOKE_OUTPUT"])
sys.argv = [
    str(adapter_path), "--repo", str(core), "--request", str(request),
    "--output", str(output), "--engine", engine,
]
if engine == "structure":
    sys.argv += ["--provider", "docling"]
adapter.main()

assert "Adapter smoke page" in output.read_text(encoding="utf-8")
metadata = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
assert metadata["engine"] == engine
if engine == "structure":
    assert metadata["structure_execution"]["provenance"]["provider"] == "docling"
    assert len(calls) == 3
    assert calls[0] == ("factory", "docling")
    assert calls[1][0] == "extract"
    assert calls[2] == ("close",)
else:
    assert calls == [("pipeline", "normal")]
"""
    env = {
        **os.environ,
        "ACESSILIA_BENCHMARK_ADAPTER": str(adapter.resolve()),
        "SMOKE_CORE_ROOT": str(core_root),
        "SMOKE_REQUEST": str(request),
        "SMOKE_OUTPUT": str(output),
        "SMOKE_ENGINE": engine,
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", harness],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout
