"""Manifest messages follow the current request, not the module import locale."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import i18n
from backend.core.manifest.builder import (
    reconcile_reclassified_element_processing_needs,
)
from backend.log_messages import MSG_OBLIGATION_IMAGE, MSG_OBLIGATION_TABLE
from tests.test_manifest_characterization import FIXTURES, _build


def test_manifest_messages_change_with_request_locale_without_reimport(
    tmp_path: Path,
) -> None:
    fixture = json.loads((FIXTURES / "toolbox-v2-contract.json").read_text())
    messages = []
    structures = []
    for locale in ("en_US", "pt_BR", "en_US"):
        token = i18n.set_request_locale(locale)
        try:
            manifest = _build(tmp_path, fixture, refine=False)
            table = next(o for o in manifest.obligations if o.kind == "linearize-table")
            observation = next(
                o
                for o in manifest.observations
                if o.kind == "table-requires-processing"
            )
            assert table.rationale == i18n.t(MSG_OBLIGATION_TABLE)
            assert observation.message == table.rationale
            messages.append(table.rationale)
            structure = manifest.model_dump(mode="json")
            for item in structure["observations"]:
                item.pop("message")
            for item in structure["obligations"]:
                item.pop("rationale")
            structures.append(structure)
        finally:
            i18n.reset_request_locale(token)
    assert messages[0] == messages[2] == MSG_OBLIGATION_TABLE
    assert messages[1] != messages[0]
    assert structures[0] == structures[1] == structures[2]


@pytest.mark.parametrize("locale", ["en_US", "pt_BR"])
def test_reclassified_element_messages_use_current_locale(
    tmp_path: Path, locale: str
) -> None:
    fixture = json.loads((FIXTURES / "toolbox-v2-contract.json").read_text())
    token = i18n.set_request_locale("pt_BR" if locale == "en_US" else "en_US")
    try:
        manifest = _build(tmp_path, fixture, refine=False)
    finally:
        i18n.reset_request_locale(token)
    table = next(element for element in manifest.elements if element.type == "table")
    table.type = "picture"
    token = i18n.set_request_locale(locale)
    try:
        reconcile_reclassified_element_processing_needs(
            manifest, table, previous_type="table"
        )
        obligation = next(
            o
            for o in manifest.obligations
            if o.target_ids == [table.id] and o.kind == "describe-image"
        )
        assert obligation.rationale == i18n.t(MSG_OBLIGATION_IMAGE)
        if locale == "pt_BR":
            assert obligation.rationale != MSG_OBLIGATION_IMAGE
        assert not any(
            o.kind == "linearize-table" and o.target_ids == [table.id]
            for o in manifest.obligations
        )
    finally:
        i18n.reset_request_locale(token)
