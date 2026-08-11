from scripts.filter_accelerator_requirements import (
    filter_requirements,
    normalized_requirement_name,
)


def test_normalized_requirement_name_handles_pep_503_names() -> None:
    assert normalized_requirement_name("TorchVision==0.22.1") == "torchvision"
    assert normalized_requirement_name("nvidia_cublas_cu12==12.6.4.1") == (
        "nvidia-cublas-cu12"
    )
    assert normalized_requirement_name("--index-url https://example.test") is None


def test_filter_requirements_removes_only_accelerator_distributions() -> None:
    requirements = """\
--index-url https://pypi.org/simple
torch==2.7.1
torchvision==0.22.1
triton==3.3.1
nvidia-cublas-cu12==12.6.4.1
safetensors[torch]==0.5.3
torchmetrics==1.7.1
# exported by Poetry
"""

    assert filter_requirements(requirements) == """\
--index-url https://pypi.org/simple
safetensors[torch]==0.5.3
torchmetrics==1.7.1
# exported by Poetry
"""