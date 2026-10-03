"""Exercise actual PDF page copying, navigation and failure handling."""

import pymupdf
import pytest

from backend.tools import pdf_splitter


@pytest.mark.parametrize("limit, count", [(None, 50), (2, 2), (100, 53), (0, 0), (-1, 0)])
def test_split_preserves_default_limit_names_order_and_content(tmp_path, limit, count):
    source = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        for number in range(53):
            page = document.new_page(width=300 + number, height=400)
            page.insert_text((40, 40), f"Page {number + 1}")
        document.save(source)
    outputs = (
        pdf_splitter.split_pdf(source, tmp_path)
        if limit is None else pdf_splitter.split_pdf(source, tmp_path, limit)
    )

    assert len(outputs) == count
    for number, output in enumerate(outputs):
        assert output == tmp_path / f"pagina_{number + 1:03d}.pdf"
        with pymupdf.open(output) as document:
            assert len(document) == 1
            assert document[0].rect == pymupdf.Rect(0, 0, 300 + number, 400)
            assert document[0].get_text().strip() == f"Page {number + 1}"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("limit", [1, 2])
def test_split_preserves_images_links_annotations_and_fields(tmp_path, rotation, limit):
    source = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        document.new_page(width=300, height=400)
        document.new_page(width=300, height=400)
        page = document[0]
        page.set_cropbox(pymupdf.Rect(10, 20, 290, 380))
        page.insert_text((40, 40), "Text before splitting")
        image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), 0)
        image.clear_with(120)
        page.insert_image(pymupdf.Rect(220, 40, 260, 80), pixmap=image)
        links = [
            {"kind": pymupdf.LINK_URI, "uri": "https://example.com/"},
            {"kind": pymupdf.LINK_GOTO, "page": 0, "to": pymupdf.Point(40, 40)},
            {"kind": pymupdf.LINK_GOTO, "page": 1, "to": pymupdf.Point(40, 40)},
            {"kind": pymupdf.LINK_GOTOR, "file": "other.pdf", "page": 3,
             "to": pymupdf.Point(10, 20)},
        ]
        for number, link in enumerate(links):
            page.insert_link({"from": pymupdf.Rect(40, 60 + 30 * number, 160, 80 + 30 * number), **link})
        page = document.reload_page(page)
        for link in page.get_links():
            destination = document.xref_get_key(link["xref"], "A/D")[1]
            if link["kind"] == pymupdf.LINK_GOTO and link["page"] == 1:
                document.xref_set_key(link["xref"], "Dest", destination)
                document.xref_set_key(link["xref"], "A", "null")
            elif link["kind"] == pymupdf.LINK_GOTOR:
                destination_xref = document.get_new_xref()
                document.update_object(destination_xref, destination)
                document.xref_set_key(link["xref"], "A/D", f"{destination_xref} 0 R")
        page.add_text_annot((180, 200), "Preserved note")
        field = pymupdf.Widget()
        field.field_name = "answer"
        field.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        field.field_value = "Preserved answer"
        field.rect = pymupdf.Rect(40, 250, 200, 280)
        page.add_widget(field)
        page.set_rotation(rotation)
        document[1].set_rotation((rotation + 90) % 360)
        document.save(source)
    original_bytes = source.read_bytes()

    outputs = pdf_splitter.split_pdf(source, tmp_path, max_pages=limit)

    assert source.read_bytes() == original_bytes
    with pymupdf.open(source) as original, pymupdf.open(outputs[0]) as split:
        before, after = original[0], split[0]
        assert after.rotation == before.rotation
        assert after.rect == before.rect
        assert after.get_text() == before.get_text()
        assert after.get_pixmap(dpi=72).samples == before.get_pixmap(dpi=72).samples
        assert [note.info["content"] for note in after.annots()] == ["Preserved note"]
        assert [(field.field_name, field.field_value) for field in after.widgets()] == [
            ("answer", "Preserved answer")
        ]
        actual_links = sorted(after.get_links(), key=lambda link: (link["from"].y0, link["from"].x0))
        original_links = sorted(before.get_links(), key=lambda link: (link["from"].y0, link["from"].x0))
        assert len(actual_links) == len(original_links) == 4
        for expected, actual in zip(original_links, actual_links):
            assert actual["from"] == expected["from"]
            if expected["kind"] == pymupdf.LINK_GOTO and expected["page"] == 1:
                assert actual["kind"] == pymupdf.LINK_GOTOR
                assert actual["file"] == ("pagina_002.pdf" if limit == 2 else source.as_posix())
                assert actual["page"] == (0 if limit == 2 else 1)
                original_destination = original.xref_get_key(expected["xref"], "Dest")[1]
                split_destination = split.xref_get_key(actual["xref"], "A/D")[1]
                assert split_destination.split("/XYZ", 1)[1] == original_destination.split("/XYZ", 1)[1]
            else:
                assert actual["kind"] == expected["kind"]
                for key in ("uri", "file", "page", "to", "zoom"):
                    if key in expected:
                        assert actual[key] == expected[key]
                if expected["kind"] == pymupdf.LINK_GOTOR:
                    indirect = original.xref_get_key(expected["xref"], "A/D")[1]
                    destination = original.xref_object(int(indirect.split()[0]), compressed=True)
                    assert split.xref_get_key(actual["xref"], "A/D")[1] == destination


@pytest.mark.parametrize("password", ["", "secret"])
def test_split_encrypted_pdf_without_password(tmp_path, password):
    source = tmp_path / "encrypted.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 40), "Encrypted text")
        document.save(source, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                      owner_pw="owner", user_pw=password)
    if password:
        with pytest.raises(ValueError, match="password"):
            pdf_splitter.split_pdf(source, tmp_path)
        assert not list(tmp_path.glob("pagina_*.pdf"))
    else:
        outputs = pdf_splitter.split_pdf(source, tmp_path)
        with pymupdf.open(outputs[0]) as split:
            assert split[0].get_text().strip() == "Encrypted text"


def test_split_rejects_missing_empty_and_invalid_sources(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_splitter.split_pdf(tmp_path / "missing.pdf", tmp_path)
    for content in (b"", b"Not a PDF"):
        source = tmp_path / "invalid.pdf"
        source.write_bytes(content)
        with pytest.raises(pymupdf.FileDataError):
            pdf_splitter.split_pdf(source, tmp_path)
        assert not list(tmp_path.glob("pagina_*.pdf"))


def test_split_closes_documents_when_saving_fails(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(source)
    opened = []
    native_open = pymupdf.open

    def track_open(*args, **kwargs):
        document = native_open(*args, **kwargs)
        opened.append(document)
        return document

    monkeypatch.setattr(pdf_splitter.pymupdf, "open", track_open)
    with pytest.raises(Exception):
        pdf_splitter.split_pdf(source, tmp_path / "missing-directory")
    assert len(opened) == 2
    assert all(document.is_closed for document in opened)
