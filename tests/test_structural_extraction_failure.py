"""A Toolbox failure during structural extraction fails the job explicitly.

There is no local extractor to fall back on (docs/adr/0003); the SDK has
already retried and failed over, so the orchestrator turns the error into a
message that names the capability and the kind of failure, and keeps the cause.
The message reaches the end user, so the cause's detail (internal endpoints)
stays out of it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from acessilia_sdk.toolbox import ToolboxProviderUnavailable, ToolboxUnavailable
from backend import i18n
from backend.agents import pddl_orchestrator as pddl
from tests.pddl_support import build_orchestrator


def _failing_process(error):
    def process(*args, **kwargs):
        raise error

    return process


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ToolboxProviderUnavailable("toolbox down"),
        ToolboxUnavailable(
            [("http://a.test", ToolboxProviderUnavailable("a")),
             ("http://b.test", ToolboxProviderUnavailable("b"))]
        ),
    ],
)
async def test_toolbox_failure_becomes_an_explicit_job_error(monkeypatch, tmp_path, error):
    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=_failing_process(error))

    async def must_not_run(*args, **kwargs):
        raise AssertionError("the pipeline continued after a failed extraction")

    monkeypatch.setattr(pddl, "inspect_source_media", must_not_run)

    with pytest.raises(pddl.StructuralExtractionError) as info:
        await orchestrator.executar(tmp_path / "doc.pdf", tmp_path)

    message = str(info.value)
    assert "document.structure.extract" in message
    assert type(error).__name__ in message
    assert "http://" not in message
    assert info.value.__cause__ is error


@pytest.mark.asyncio
async def test_translated_message_keeps_both_placeholders(tmp_path):
    # gen_locale_catalogs only checks that the entry exists, not that the
    # translation keeps {capability} and {error}.
    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(
        process=_failing_process(ToolboxProviderUnavailable("toolbox down"))
    )

    token = i18n.set_request_locale("pt_BR")
    try:
        with pytest.raises(pddl.StructuralExtractionError) as info:
            await orchestrator.executar(tmp_path / "doc.pdf", tmp_path)
    finally:
        i18n.reset_request_locale(token)

    message = str(info.value)
    assert message.startswith("A extração estrutural falhou")
    assert "document.structure.extract" in message
    assert "ToolboxProviderUnavailable" in message
    assert "{" not in message


@pytest.mark.asyncio
async def test_non_toolbox_errors_are_not_rewrapped(tmp_path):
    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(
        process=_failing_process(FileNotFoundError("missing source"))
    )

    with pytest.raises(FileNotFoundError, match="missing source"):
        await orchestrator.executar(tmp_path / "doc.pdf", tmp_path)
