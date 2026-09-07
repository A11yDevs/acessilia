from backend.tools.validators import (
    is_extension_allowed,
    is_file_size_allowed,
    validate_file,
)


def test_valid_extension():
    assert is_extension_allowed("document.pdf") is True
    assert is_extension_allowed("image.png") is True
    assert is_extension_allowed("photo.jpg") is True


def test_invalid_extension():
    assert is_extension_allowed("script.exe") is False
    assert is_extension_allowed("archive.zip") is False


def test_file_size_within_limit():
    assert is_file_size_allowed(1024 * 1024) is True


def test_file_size_exceeds_limit():
    assert is_file_size_allowed(1024 * 1024 * 100) is False


def test_validate_file_valid():
    valid, msg = validate_file("test.pdf", 1024 * 1024)
    assert valid is True
    assert msg == ""


def test_validate_file_invalid_ext():
    valid, msg = validate_file("test.exe", 1024 * 1024)
    assert valid is False
    assert "suportado" in msg.lower()


def test_validate_file_rejects_docx_and_html_in_legacy(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "pipeline_engine", "legacy")

    for filename in ("documento.docx", "pagina.html"):
        valid, msg = validate_file(filename, 1024 * 1024)
        assert valid is False
        assert "legacy" in msg.lower()


def test_validate_file_allows_docx_and_html_outside_legacy(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "pipeline_engine", "pddl")

    for filename in ("documento.docx", "pagina.html"):
        valid, msg = validate_file(filename, 1024 * 1024)
        assert valid is True
        assert msg == ""
