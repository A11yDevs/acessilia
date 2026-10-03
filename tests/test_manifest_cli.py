"""Manifest CLIs use Toolbox, preserve language and report unsupported OCR control."""

import json
from unittest.mock import AsyncMock

import fitz
import pytest

from backend.core.manifest.schema import validate_manifest
from backend.tools.toolbox_client import ToolboxClient
from scripts import manifest, pmv


@pytest.mark.parametrize("cli", [manifest, pmv])
def test_manifest_cli_extracts_through_toolbox(cli, monkeypatch, tmp_path):
    source = tmp_path / "document.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Accessible content")
        pdf.save(source)
    response = {
        "status": "succeeded", "provider": "docling",
        "document": {
            "title": "Document", "elements": [{
                "id": "paragraph-1", "type": "paragraph", "raw_label": "paragraph",
                "text": "Accessible content", "reading_order": 1,
                "hierarchy_level": 0, "page_number": 1,
            }],
            "pages": [{"page_number": 1, "width": 595, "height": 842,
                       "element_ids": ["paragraph-1"]}],
            "summary": {"page_count": 1, "element_count": 1,
                        "observation_count": 0, "obligation_count": 0,
                        "element_types": {"paragraph": 1}},
        },
    }
    upload = AsyncMock(return_value="artifact-1")
    extract = AsyncMock(return_value=response)
    monkeypatch.setattr(ToolboxClient, "upload_artifact", upload)
    monkeypatch.setattr(ToolboxClient, "extract_structure", extract)
    from backend.config.settings import settings
    monkeypatch.setattr(settings, "toolbox_use_artifact_store", True)
    output = tmp_path / "manifest.json"
    args = [str(source), "-o", str(output), "--language", "en-US"]
    if cli is pmv:
        args.insert(0, "manifest")

    assert cli.main(args) == 0
    payload = json.loads(output.read_text())
    assert validate_manifest(payload) == []
    assert payload["language"] == "en-US"
    assert payload["elements"][0]["text"] == "Accessible content"
    upload.assert_awaited_once_with(source.resolve())
    assert extract.call_args.kwargs["language"] == "en-US"
    assert extract.call_args.kwargs["artifact_id"] == "artifact-1"


@pytest.mark.parametrize("cli", [manifest, pmv])
def test_manifest_cli_rejects_unsupported_no_ocr(cli, tmp_path, capsys):
    output = tmp_path / "manifest.json"
    args = [str(tmp_path / "document.pdf"), "-o", str(output), "--no-ocr"]
    if cli is pmv:
        args.insert(0, "manifest")

    assert cli.main(args) == 1
    assert "--no-ocr is unsupported" in capsys.readouterr().err
    assert not output.exists()
