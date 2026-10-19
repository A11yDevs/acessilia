"""Provider configuration must honor environment changes after module import."""

import pytest

from acessilia_sdk.toolbox.capabilities import provider_default

from backend.config.settings import Settings


@pytest.mark.parametrize(
    "attribute,environment,default",
    [
        ("fusion_hybrid_provider", "FUSION_HYBRID_PROVIDER", "mineru-hyb"),
        ("toolbox_page_ocr_provider", "TOOLBOX_PAGE_OCR_PROVIDER", provider_default("toolbox_page_ocr_provider")),
        ("toolbox_adjudicate_provider", "TOOLBOX_ADJUDICATE_PROVIDER", provider_default("toolbox_adjudicate_provider")),
        ("toolbox_orientation_provider", "TOOLBOX_ORIENTATION_PROVIDER", provider_default("toolbox_orientation_provider")),
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
