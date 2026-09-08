"""
What this suite verifies: that validate_file and its building-block helpers enforce the configured
extension whitelist and size limit, and that their user-facing error messages resolve through the active
locale strings files under each supported locale (en_US identity lookup vs pt_BR translations).
"""

from backend.config.settings import settings
from backend.i18n import _catalog_for
from backend.tools.validators import (
    is_extension_allowed,
    is_file_size_allowed,
    validate_file,
)


def test_valid_extension():
    """Known accepted extensions should map to True from the lowercase-suffix check."""
    assert is_extension_allowed("document.pdf") is True
    assert is_extension_allowed("image.png") is True
    assert is_extension_allowed("photo.jpg") is True


def test_invalid_extension():
    """Extensions outside settings.allowed_extensions should map to False from the lowercase-suffix check."""
    assert is_extension_allowed("script.exe") is False
    assert is_extension_allowed("archive.zip") is False


def test_file_size_within_limit():
    """A size at or under the configured byte limit should pass validation."""
    assert is_file_size_allowed(1024 * 1024) is True


def test_file_size_exceeds_limit():
    """A size far above the configured byte limit should fail validation."""
    assert is_file_size_allowed(1024 * 1024 * 100) is False


def test_validate_file_valid():
    """An allowed extension within the size limit should validate true with an empty reason message."""
    valid, msg = validate_file("test.pdf", 1024 * 1024)
    assert valid is True
    assert msg == ""


def test_validate_file_invalid_ext(monkeypatch):
    """Under pt_BR an unsupported extension should fail with the catalog-translated Portuguese reason text."""
    monkeypatch.setenv("LOCALE", "pt_BR")
    _catalog_for.cache_clear()
    valid, msg = validate_file("test.exe", 1024 * 1024)
    assert valid is False
    assert "suportado" in msg.lower()


def test_validate_file_invalid_ext_en_us(monkeypatch):
    """Under en_US the same unsupported extension should yield the canonical English reason text."""
    monkeypatch.setenv("LOCALE", "en_US")
    _catalog_for.cache_clear()
    valid, msg = validate_file("test.exe", 1024 * 1024)
    assert valid is False
    assert msg == "Unsupported file format. Send PDF, DOCX, HTML, PNG, JPG, TIFF, BMP or WEBP."


def test_validate_file_invalid_size_localized(monkeypatch):
    """An oversized file should fail with the limit value substituted into each locale's own localized template text."""
    monkeypatch.setattr(settings, "max_file_size_mb", 5)
    _catalog_for.cache_clear()

    monkeypatch.setenv("LOCALE", "en_US")
    valid_en, msg_en = validate_file("test.pdf", 1 << 40)
    assert valid_en is False
    assert msg_en == "File too large. Limit: 5 MB."

    monkeypatch.setenv("LOCALE", "pt_BR")
    _catalog_for.cache_clear()
    valid_pt, msg_pt = validate_file("test.pdf", 1 << 40)
    assert valid_pt is False
    assert msg_pt == "Arquivo muito grande. Limite: 5 MB."
