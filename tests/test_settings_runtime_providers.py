"""Provider configuration must honor environment changes after module import."""

import pytest

from backend.config.settings import Settings


@pytest.mark.parametrize(
    "attribute,environment,default",
    [
        ("fusion_hybrid_provider", "FUSION_HYBRID_PROVIDER", "mineru-hyb"),
        ("toolbox_page_ocr_provider", "TOOLBOX_PAGE_OCR_PROVIDER", "qwen3-vl-page"),
        ("toolbox_adjudicate_provider", "TOOLBOX_ADJUDICATE_PROVIDER", "qwen3-vl-judge"),
        ("toolbox_orientation_provider", "TOOLBOX_ORIENTATION_PROVIDER", "rapidocr-orient"),
    ],
)
def test_provider_environment_is_read_at_instantiation(
    monkeypatch, tmp_path, attribute, environment, default
):
    paths = dict(temp_dir=tmp_path / "temp", data_dir=tmp_path / "data", logs_dir=tmp_path / "logs")
    monkeypatch.delenv(environment, raising=False)
    original = Settings(**paths)
    assert getattr(original, attribute) == default

    monkeypatch.setenv(environment, "custom-provider")
    configured = Settings(**paths)
    assert getattr(configured, attribute) == "custom-provider"
    assert getattr(original, attribute) == default
