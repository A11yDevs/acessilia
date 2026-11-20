"""Tests for ``docstruct.fusion.noise.is_legitimate_text``."""
from __future__ import annotations

import pytest

from docstruct.fusion import is_legitimate_text


@pytest.mark.parametrize(
    "text",
    [
        "This is a legitimate body paragraph extracted from a document.",
        "Section 2: Methods and results",
        "Intro",
    ],
)
def test_accepts_legitimate_prose(text: str):
    assert is_legitimate_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "42",
        "Page 12",
        "ab",  # fewer than 3 letters
        "!!! ### $$$ %%% aaa",  # < 40% alphanumeric
        "aaaaaa",  # repeated single character (junk)
        "x y z w q",  # low token quality
    ],
)
def test_rejects_noise_and_non_prose(text: str | None):
    assert is_legitimate_text(text) is False


def test_respects_custom_min_quality_threshold():
    # Two real words plus two single-letter noise tokens: quality = 2/4 = 0.5
    sample = "hello world x z"
    assert is_legitimate_text(sample, min_quality=0.45) is True
    assert is_legitimate_text(sample, min_quality=0.60) is False
