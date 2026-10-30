"""A document without a heading is titled by the uploaded name, never the upload's UUID (#333)."""

from types import SimpleNamespace

import pytest

from tests.test_api import api_paths as api_paths_fixture
from tests.test_pending_fixes import isolated_runtime as runtime_fixture

isolated_runtime = runtime_fixture
api_paths = api_paths_fixture

#: The API stores uploads as ``<uuid4 hex><suffix>``.
STORED = "862b52bffbef42d096e8dc1f8e0142c9.pdf"
UPLOADED = "51-pages.pdf"


def _untitled_payload() -> dict:
    """An agent result whose blocks have no heading, so no title can be inferred."""
    return {
        "text": "Conteudo simples, sem titulo.",
        "pages": [{"blocks": [{"type": "paragraph", "text": "Conteudo simples, sem titulo."}]}],
    }


def _patch_pipeline(monkeypatch, *, cached=None):
    from backend import service

    async def get_cached(*args):
        return cached

    async def execute(*args, **kwargs):
        return _untitled_payload()

    async def ignore(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "get_cached", get_cached)
    monkeypatch.setattr(service, "set_cache", ignore)
    monkeypatch.setattr(service, "drop_cache", ignore)
    monkeypatch.setattr(service, "agente", SimpleNamespace(executar=execute))


@pytest.mark.asyncio
@pytest.mark.parametrize("from_cache", [False, True], ids=["processed", "cache-hit"])
async def test_untitled_document_takes_the_uploaded_name(
    isolated_runtime, monkeypatch, tmp_path, from_cache
):
    from backend import service

    source = tmp_path / STORED
    source.write_bytes(b"%PDF")
    _patch_pipeline(monkeypatch, cached=_untitled_payload() if from_cache else None)

    document = await service.process(
        source, task_id=f"untitled-{from_cache}", display_filename=UPLOADED
    )

    assert document["title"] == "51-pages"
    assert document["source"]["name"] == UPLOADED
    assert STORED.removesuffix(".pdf") not in str(document["title"])


@pytest.mark.asyncio
async def test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name(
    isolated_runtime, monkeypatch, tmp_path
):
    from backend import service

    source = tmp_path / STORED
    source.write_bytes(b"%PDF")
    _patch_pipeline(monkeypatch)

    document = await service.process(
        source, task_id="untitled-path", display_filename="../../etc/relat\u00f3rio.pdf"
    )

    assert document["title"] == "relat\u00f3rio"
    assert document["source"]["name"] == "relat\u00f3rio.pdf"


@pytest.mark.asyncio
async def test_without_an_uploaded_name_the_file_name_is_still_the_fallback(
    isolated_runtime, monkeypatch, tmp_path
):
    """Callers that process a file of their own (CLI, tests) keep the old fallback."""
    from backend import service

    source = tmp_path / "relatorio-local.pdf"
    source.write_bytes(b"%PDF")
    _patch_pipeline(monkeypatch)

    document = await service.process(source, task_id="untitled-local")

    assert document["title"] == "relatorio-local"


@pytest.mark.asyncio
async def test_the_worker_passes_the_uploaded_name_to_the_pipeline(api_paths, monkeypatch):
    from backend.agents.state_manager import state_manager
    from backend.api.worker import ApiJob, JobExecutor

    task_id = "untitled-worker"
    stored = api_paths / STORED
    stored.write_bytes(b"%PDF")
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()
    seen: dict = {}

    async def fake_process(*args, **kwargs):
        seen.update(kwargs)
        state_manager.criar_tarefa(stored, task_id=task_id)
        return {"title": "51-pages", "sections": []}

    monkeypatch.setattr("backend.service.process", fake_process)

    await JobExecutor().run(
        ApiJob(
            task_id=task_id,
            file_path=stored,
            filename=UPLOADED,
            output_dir=api_paths / "output" / task_id,
        )
    )

    assert seen["display_filename"] == UPLOADED
