"""A document without a heading is titled by the uploaded name, never the upload's UUID (#333)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.core_config_support import core_config, toolbox_config
from tests.test_pending_fixes import isolated_runtime as runtime_fixture

isolated_runtime = runtime_fixture

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
    monkeypatch.setattr(service, "agente", SimpleNamespace(execute=execute))
    monkeypatch.setattr(service, "_salvar_json_canonico", lambda *a, **k: None)


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
        source, task_id=f"untitled-{from_cache}", display_filename=UPLOADED,
        config=core_config(),
    )

    assert document["title"] == "51-pages"
    assert document["source"]["name"] == UPLOADED
    from acessilia_core.export.renderers.html_renderer import render_html

    html = render_html(document, tmp_path / "result.html").read_text(encoding="utf-8")
    assert "<title>51-pages</title>" in html
    assert '<main aria-label="51-pages"' in html
    assert STORED.removesuffix(".pdf") not in str(document["title"])


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", [
    '../../etc/relat\xf3rio.pdf', '..\\..\\etc\\relat\xf3rio.pdf', 'C:\\fakepath\\relat\xf3rio.pdf',
    '..\\etc/relat\xf3rio.pdf',
])
async def test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name(
    isolated_runtime, monkeypatch, tmp_path, filename
):
    from backend import service

    source = tmp_path / STORED
    source.write_bytes(b"%PDF")
    _patch_pipeline(monkeypatch)

    document = await service.process(
        source, task_id="untitled-path", display_filename=filename,
        config=core_config(),
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

    document = await service.process(source, task_id="untitled-local", config=core_config())

    assert document["title"] == "relatorio-local"


@pytest.mark.asyncio
async def test_the_worker_passes_the_uploaded_name_to_the_pipeline(
    isolated_runtime, tmp_path, monkeypatch
):
    from backend.api.worker import ApiJob, JobExecutor
    from backend.config.settings import settings

    task_id = "untitled-worker"
    _, manager = isolated_runtime
    stored = tmp_path / STORED
    stored.write_bytes(b"%PDF")
    seen: dict = {}

    async def fake_process(*args, **kwargs):
        seen.update(kwargs)
        if manager.obter(task_id) is None:
            manager.criar_tarefa(stored, task_id=task_id)
        from acessilia_core.pipeline.canonical_builder import build_canonical_document
        return build_canonical_document(_untitled_payload(), title="51-pages", toolbox=toolbox_config())

    monkeypatch.setattr("backend.service.process", fake_process)

    monkeypatch.setattr(settings, "toolbox_docx_enabled", False)
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", False)
    executor = JobExecutor()
    try:
        await executor.run(
            ApiJob(
                task_id=task_id,
                file_path=stored,
                filename=UPLOADED,
                output_dir=tmp_path / "output" / task_id,
            )
        )
        assert seen["display_filename"] == UPLOADED
        assert manager.obter(task_id)["status"] == "done"
    finally:
        executor._executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('filename', [
    '../../etc/relat\xf3rio.pdf', '..\\..\\etc\\relat\xf3rio.pdf', 'C:\\fakepath\\relat\xf3rio.pdf',
])
async def test_api_keeps_only_the_uploaded_basename(isolated_runtime, filename):
    import httpx

    from backend.api.app import create_app
    from backend.services.job_store import load_record

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app()), base_url='http://test'
    ) as client:
        response = await client.post('/api/v1/jobs', files={
            'document_file': (filename, b'%PDF', 'application/pdf'),
        })
    assert response.status_code == 202
    record = load_record(response.json()['task_id'])
    assert record['request']['filename'] == 'relat\xf3rio.pdf'
    stored_name = Path(record['request']['file_path']).name
    assert stored_name != record['request']['filename']
    assert stored_name.endswith('.pdf')


@pytest.mark.asyncio
@pytest.mark.parametrize("from_cache", [False, True], ids=["processed", "cache-hit"])
async def test_the_canonical_build_takes_the_job_toolbox_config(
    isolated_runtime, monkeypatch, tmp_path, from_cache
):
    """ADR-0016 step 3: the formulas are enriched on the job's Toolbox, on both paths."""
    from backend import service

    source = tmp_path / STORED
    source.write_bytes(b"%PDF")
    _patch_pipeline(monkeypatch, cached=_untitled_payload() if from_cache else None)
    build = service.build_canonical_document
    toolboxes = []

    def recording_build(*args, toolbox, **kwargs):
        toolboxes.append(toolbox)
        return build(*args, toolbox=toolbox, **kwargs)

    monkeypatch.setattr(service, "build_canonical_document", recording_build)
    job_config = core_config(toolbox={"retries": 7})

    await service.process(
        source, task_id=f"toolbox-{from_cache}", display_filename=UPLOADED, config=job_config,
    )

    assert toolboxes == [job_config.toolbox] and toolboxes[0] is job_config.toolbox


@pytest.mark.asyncio
async def test_the_processing_cache_is_keyed_by_the_job_config(isolated_runtime, monkeypatch, tmp_path):
    """#544: the key a job reads and writes describes its config, not the settings."""
    from backend import service

    source = tmp_path / STORED
    source.write_bytes(b"%PDF")
    _patch_pipeline(monkeypatch)
    keys = []

    async def get_cached(_path, extra):
        keys.append(extra)
        return None

    monkeypatch.setattr(service, "get_cached", get_cached)
    job_config = core_config(fusion={"secondary_provider": "only-in-the-job-config"})

    await service.process(source, task_id="cache-key", config=job_config)

    assert keys == [service._cache_version(job_config, "normal", None, False)]
    assert keys[0] != service._cache_version(core_config(), "normal", None, False)
