"""Keeps every Toolbox call behind the core's capability registry.

``backend/config/toolbox_capabilities.py`` is the allowlist of Toolbox
contracts the core may call. These tests make sure the clients cannot bypass
it, that settings take their provider defaults from it, and that the shared
transport in ``execute_capability`` behaves the same for every client.
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
from pathlib import Path

import httpx
import pytest
import respx

from backend.config import settings as settings_module
from backend.config.toolbox_capabilities import (
    PROVIDER_DEFAULTS,
    TOOLBOX_CAPABILITIES,
)
from backend.tools.toolbox_adjudicate_client import ToolboxAdjudicateClient
from backend.tools.toolbox_client import (
    ToolboxCapabilityError,
    ToolboxContractViolation,
    execute_capability,
    run_sync,
)
from backend.tools.toolbox_orientation_client import ToolboxOrientationClient
from backend.tools.toolbox_page_ocr_client import ToolboxPageOcrClient

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
TOOLS_DIR = BACKEND_DIR / "tools"
BASE_URL = "http://toolbox.test"

_EXECUTE_LITERAL_RE = re.compile(
    r"/v1/capabilities/[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+:execute"
)


def _capability_constants() -> dict[str, str]:
    """``*CAPABILITY*`` string constants declared by the client modules."""
    found: dict[str, str] = {}
    for path in sorted(TOOLS_DIR.glob("toolbox_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and "CAPABILITY" in target.id
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    found[f"{path.name}:{target.id}"] = node.value.value
    return found


def test_client_capability_constants_are_registered_for_execute() -> None:
    constants = _capability_constants()
    assert constants, "no capability constants found in backend/tools"
    unregistered = {
        name: capability
        for name, capability in constants.items()
        if capability not in TOOLBOX_CAPABILITIES
        or TOOLBOX_CAPABILITIES[capability].transport != "execute"
    }
    assert not unregistered, (
        f"client constants outside TOOLBOX_CAPABILITIES: {unregistered}"
    )


def test_no_module_hardcodes_an_execute_route() -> None:
    """Every ``:execute`` call goes through ``execute_capability``.

    A hard-coded route would skip the allowlist check, so the registry would no
    longer describe what the core actually calls.
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {literal}"
        for path in sorted(BACKEND_DIR.rglob("*.py"))
        for line, literal in _code_string_literals(path)
        if _EXECUTE_LITERAL_RE.search(literal)
    ]
    assert not offenders, "hard-coded execute routes:\n" + "\n".join(offenders)


def _code_string_literals(path: Path) -> list[tuple[int, str]]:
    """String literals used as values, i.e. everything except docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_provider_settings_default_to_the_registry() -> None:
    fields = settings_module.Settings.__dataclass_fields__
    for setting, default in PROVIDER_DEFAULTS.items():
        assert setting in fields, f"Settings has no attribute {setting}"
        if setting.upper() in os.environ:
            continue  # overridden by the environment running the tests
        assert fields[setting].default == default, setting


def test_every_provider_setting_is_used_by_a_capability() -> None:
    used = {
        capability.provider_setting
        for capability in TOOLBOX_CAPABILITIES.values()
        if capability.provider_setting
    }
    assert set(PROVIDER_DEFAULTS) == used


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability_id", "message"),
    [
        ("music.omr", "não registrada"),
        ("dataset.sync", "não é executada via :execute"),
    ],
)
async def test_execute_refuses_capabilities_outside_the_allowlist(
    capability_id: str, message: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url__regex=r".*")
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(ToolboxCapabilityError, match=message):
                await execute_capability(
                    http,
                    capability_id,
                    provider="any",
                    upload=("x.txt", b"x", "text/plain"),
                )
        assert not route.called


@pytest.mark.asyncio
async def test_execute_rejects_a_non_json_response() -> None:
    with respx.mock() as router:
        router.post(f"{BASE_URL}/v1/capabilities/document.ocr:execute").mock(
            return_value=httpx.Response(200, text="<html>proxy error</html>")
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(ToolboxContractViolation, match="JSON válido"):
                await execute_capability(
                    http,
                    "document.ocr",
                    provider="docling-ocr",
                    artifact_id="a1",
                )


@pytest.mark.asyncio
async def test_execute_rejects_a_non_object_response() -> None:
    with respx.mock() as router:
        router.post(f"{BASE_URL}/v1/capabilities/document.ocr:execute").mock(
            return_value=httpx.Response(200, json=["not", "an", "envelope"])
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(ToolboxContractViolation, match="objeto JSON"):
                await execute_capability(
                    http,
                    "document.ocr",
                    provider="docling-ocr",
                    artifact_id="a1",
                )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_cls", "capability_id", "call"),
    [
        (
            ToolboxPageOcrClient,
            "document.ocr.page",
            lambda client: client.transcribe(artifact_id="a1"),
        ),
        (
            ToolboxAdjudicateClient,
            "document.adjudicate.page",
            lambda client: client.judge_page("a", "b", artifact_id="a1"),
        ),
        (
            ToolboxOrientationClient,
            "image.page.orient",
            lambda client: client.detect(artifact_id="a1"),
        ),
    ],
)
async def test_clients_send_the_configured_api_key(
    client_cls, capability_id: str, call
) -> None:
    """These three clients used to send a literal ``******`` instead of the key."""
    client = client_cls(base_url=BASE_URL, api_key="secret-key")
    try:
        with respx.mock() as router:
            route = router.post(
                f"{BASE_URL}/v1/capabilities/{capability_id}:execute"
            ).mock(
                return_value=httpx.Response(
                    200, json={"status": "succeeded", "document": {}}
                )
            )
            await call(client)
        assert route.calls.last.request.headers["Authorization"] == (
            "Bearer secret-key"
        )
    finally:
        await client.close()


def test_run_sync_outside_an_event_loop() -> None:
    async def value() -> int:
        return 42

    assert run_sync(value()) == 42


@pytest.mark.asyncio
async def test_run_sync_inside_a_running_event_loop() -> None:
    """``asyncio.run`` would raise here; ``run_sync`` moves to a worker thread."""

    async def value() -> str:
        await asyncio.sleep(0)
        return "ok"

    assert run_sync(value()) == "ok"
