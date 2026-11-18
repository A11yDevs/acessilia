"""The pure format identity is data that callers can serialize and share."""

from dataclasses import FrozenInstanceError, asdict
import pytest
from docstruct.export.formats import FormatSpec


def test_format_spec_preserves_binding_identity_and_is_immutable():
    spec = FormatSpec("pdf_ua", "1", "application/pdf", "pdf", "remote")
    assert asdict(spec) == {
        "id": "pdf_ua", "version": "1", "media_type": "application/pdf",
        "extension": "pdf", "execution": "remote",
    }
    with pytest.raises(FrozenInstanceError):
        spec.extension = "pdf_ua.pdf"
