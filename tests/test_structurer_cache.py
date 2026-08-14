from pathlib import Path
from types import SimpleNamespace

from backend.tools import structurer


def test_hydrate_rapidocr_models_copies_only_missing_files(
    monkeypatch, tmp_path: Path
) -> None:
    models_dir = tmp_path / "package-models"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model_name = next(iter(structurer.RAPIDOCR_MODEL_FILENAMES))
    (cache_dir / model_name).write_bytes(b"cached-model")
    monkeypatch.setattr(structurer, "_rapidocr_models_dir", lambda: models_dir)
    monkeypatch.setattr(structurer.settings, "rapidocr_cache_dir", cache_dir)

    structurer._hydrate_rapidocr_models()

    assert (models_dir / model_name).read_bytes() == b"cached-model"


def test_persist_rapidocr_models_copies_downloaded_files(
    monkeypatch, tmp_path: Path
) -> None:
    models_dir = tmp_path / "package-models"
    cache_dir = tmp_path / "cache"
    models_dir.mkdir()
    model_name = next(iter(structurer.RAPIDOCR_MODEL_FILENAMES))
    (models_dir / model_name).write_bytes(b"downloaded-model")
    monkeypatch.setattr(structurer, "_rapidocr_models_dir", lambda: models_dir)
    monkeypatch.setattr(structurer.settings, "rapidocr_cache_dir", cache_dir)

    structurer._persist_rapidocr_models()

    assert (cache_dir / model_name).read_bytes() == b"downloaded-model"


def test_docling_processing_persists_models_after_conversion(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"pdf")
    expected_document = object()
    converter = SimpleNamespace(
        convert=lambda path: SimpleNamespace(document=expected_document)
    )
    persist_calls = []
    docling_structurer = structurer.DoclingStructurer()
    monkeypatch.setattr(docling_structurer, "_get_converter", lambda: converter)
    monkeypatch.setattr(
        structurer, "_persist_rapidocr_models", lambda: persist_calls.append(True)
    )

    assert docling_structurer._process_document(source) is expected_document
    assert persist_calls == [True]