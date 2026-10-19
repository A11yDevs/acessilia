"""Provider configuration for the capabilities added in PR #125.

The clients themselves are tested in ``libs/sdk/tests/clients/test_vlm_clients.py``.
"""
from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Provider registration (providers-config-vlm.yaml)
# ---------------------------------------------------------------------------

CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "drbench" / "experiments" / "slurm" / "providers-config-vlm.yaml"
)

PR125_CAPABILITIES = {
    "document.ocr.page": {"qwen3-vl-page", "dots-ocr-page", "deepseek-ocr-page", "teleocr-page"},
    "document.adjudicate.page": {"qwen3-vl-judge"},
    "document.adjudicate.region": {"qwen3-vl-judge"},
    "image.page.orient": {"rapidocr-orient"},
}


def _providers_by_capability() -> dict[str, set[str]]:
    import yaml

    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for provider in data["providers"]:
        for capability in provider["capabilities"]:
            out.setdefault(capability, set()).add(provider["id"])
    return out


def test_pr125_capabilities_are_registered():
    by_cap = _providers_by_capability()
    for capability, providers in PR125_CAPABILITIES.items():
        assert capability in by_cap, f"capacidade {capability} não registrada"
        assert providers <= by_cap[capability], (
            f"{capability}: faltam {providers - by_cap[capability]}"
        )


def test_pr125_providers_declare_their_capabilities():
    import yaml

    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    ids = {p["id"] for p in data["providers"]}
    expected = set().union(*PR125_CAPABILITIES.values())
    assert expected <= ids, f"providers ausentes: {expected - ids}"


def test_client_capability_constants_match_the_config():
    from acessilia_sdk.toolbox.clients.adjudicate import (
        PAGE_CAPABILITY,
        REGION_CAPABILITY,
    )
    from acessilia_sdk.toolbox.clients.orientation import (
        CAPABILITY as ORIENTATION_CAPABILITY,
    )
    from acessilia_sdk.toolbox.clients.page_ocr import CAPABILITY as PAGE_OCR_CAPABILITY

    by_cap = _providers_by_capability()
    for capability in (
        PAGE_OCR_CAPABILITY,
        PAGE_CAPABILITY,
        REGION_CAPABILITY,
        ORIENTATION_CAPABILITY,
    ):
        assert capability in by_cap, f"{capability} não está no providers-config"


# ---------------------------------------------------------------------------
# mineru-hyb provider (the B source of the confirmed leaderboard best)
# ---------------------------------------------------------------------------


def test_mineru_hyb_provider_is_registered():
    import yaml

    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    providers = {p["id"]: p for p in data["providers"]}
    assert "mineru-hyb" in providers
    hyb = providers["mineru-hyb"]
    assert hyb["config"]["backend"] == "hybrid-engine"
    assert "document.structure.extract" in hyb["capabilities"]


def test_mineru_hyb_is_usable_as_the_fusion_secondary_provider():
    from backend.config.settings import settings

    assert settings.fusion_hybrid_provider == "mineru-hyb"
    # O default da fusão dual continua sendo o mineru clássico; adotar o híbrido
    # é uma escolha explícita via FUSION_SECONDARY_PROVIDER.
    assert settings.fusion_secondary_provider == "mineru"
