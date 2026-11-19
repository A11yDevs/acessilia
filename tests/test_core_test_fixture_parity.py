"""The core's local copies of the fixtures stay byte-identical to the originals."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

COPIED_FIXTURES = (
    "toolbox-contract.json",
    "toolbox-v2-contract.json",
    "manifests/toolbox-v2-contract.json",
    "manifests/two-pages-refined.json",
    "images/sunset-skyline.jpeg",
    "tutorials/java-oo-3pgs.pdf",
    "export_schema_gate/compatibility.json",
)


@pytest.mark.parametrize("relative", COPIED_FIXTURES)
def test_the_core_copy_matches_the_service_fixture(relative: str) -> None:
    """A copy is deliberate (the core suite runs without the service tree), but
    it must not drift silently when the original is refreshed."""
    assert (ROOT / "libs" / "core" / "tests" / "fixtures" / relative).read_bytes() == (
        ROOT / "tests" / "fixtures" / relative
    ).read_bytes()
