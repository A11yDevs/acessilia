from backend.export.exporters.drbench_md_exporter import export_drbench_md


def test_canonical_document_is_rendered_from_its_sections(tmp_path):
    canonical = {
        "title": "Paper",
        "sections": [
            {
                "level": 1,
                "title": "",
                "blocks": [
                    {"type": "paragraph", "text": "Body"},
                    {"type": "math", "text": "$$x^2$$"},
                ],
            }
        ],
    }

    out = export_drbench_md(canonical, tmp_path / "doc.drbench.md")

    assert out.read_text(encoding="utf-8") == "# Paper\n\nBody\n\n$$\nx^2\n$$\n"


def test_plain_text_is_written_as_is(tmp_path):
    out = export_drbench_md("# Raw\n", tmp_path / "doc.drbench.md")

    assert out.read_text(encoding="utf-8") == "# Raw\n"
