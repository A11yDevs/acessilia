"""E1.2b: the old acceptance matrix, newly rejected inputs and retained outputs."""

from copy import deepcopy
import json
from pathlib import Path
import traceback

import pytest

from acessilia_core.export import pandoc_exporter
from acessilia_core.export.messages import MSG_CANONICAL_SCHEMA_FAILED
from acessilia_core.i18n import t, set_request_locale, reset_request_locale
from docstruct.schemas import accessible_document_schema
from jsonschema import Draft202012Validator
from core_config_support import export_config, toolbox_config

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((Path(__file__).parent / 'fixtures/export_schema_gate/compatibility.json').read_text())


def _document(case):
    document = deepcopy(MATRIX['base_document'])
    for operation in case['changes']:
        target = document
        for key in operation['path'][:-1]:
            target = target[key]
        if operation.get('remove'):
            del target[operation['path'][-1]]
        else:
            target[operation['path'][-1]] = deepcopy(operation['value'])
    return document


@pytest.fixture(autouse=True)
def _english():
    token = set_request_locale('en_US')
    try:
        yield
    finally:
        reset_request_locale(token)


@pytest.mark.parametrize('case', MATRIX['cases'], ids=lambda case: case['id'])
@pytest.mark.parametrize('format_name', ['txt', 'html', 'docx', 'pdf_ua'])
def test_strict_gate_compatibility_matrix(case, format_name, tmp_path, monkeypatch):
    document = _document(case)
    before = deepcopy(document)
    output = tmp_path / 'new-directory' / ('result.' + format_name)
    calls = []

    def remote(ast, destination, **kwargs):
        calls.append(ast)
        destination.write_bytes(b'remote artifact')
        return {}

    monkeypatch.setattr(pandoc_exporter, 'toolbox_export_docx', remote)
    monkeypatch.setattr(pandoc_exporter, 'toolbox_export_pdf_ua', remote)
    options = dict(format_name=format_name, export=export_config(
        toolbox_docx_enabled=True, toolbox_pdf_ua_enabled=True,
    ), toolbox=toolbox_config())
    if case['strict_outcome'] == 'exported':
        assert pandoc_exporter.export_accessible_document(document, output, **options) == output
        assert output.is_file()
        if format_name == 'txt':
            assert output.read_text(encoding='utf-8') == case['baseline_text']
        assert bool(calls) is (format_name in {'docx', 'pdf_ua'})
    else:
        def unexpected(*args, **kwargs):
            pytest.fail('Rejected input reached a serializer or AST builder')

        monkeypatch.setattr(pandoc_exporter, 'build_pandoc_ast', unexpected)
        monkeypatch.setattr('acessilia_core.export.renderers.html_renderer.render_html', unexpected)
        monkeypatch.setattr('acessilia_core.export.renderers.txt_renderer.render_txt', unexpected)
        if case['strict_outcome'] == 'schema-rejected':
            path = '/' + '/'.join(str(part) for part in case['schema_path'])
            expected = t(MSG_CANONICAL_SCHEMA_FAILED).format(path=path, rule=case['schema_rule'])
        else:
            expected = None
        with pytest.raises(ValueError) as error:
            pandoc_exporter.export_accessible_document(document, output, **options)
        if expected:
            assert str(error.value) == expected
        else:
            assert str(error.value).startswith('Audit failed:')
        assert not calls
        assert not output.parent.exists()
        output.parent.mkdir()
        output.write_bytes(b'existing artifact')
        with pytest.raises(ValueError):
            pandoc_exporter.export_accessible_document(document, output, **options)
        assert output.read_bytes() == b'existing artifact'
    assert document == before


@pytest.mark.parametrize('case', MATRIX['cases'], ids=lambda case: case['id'])
def test_matrix_schema_classification_uses_normalized_document(case):
    normalized = pandoc_exporter._ensure_document(_document(case), title='Document', toolbox=None)
    validator = Draft202012Validator(accessible_document_schema())
    assert validator.is_valid(normalized) is case['normalized_schema_valid']


@pytest.mark.parametrize('locale', ['en_US', 'pt_BR'])
def test_schema_diagnostic_is_localized_without_document_values(locale, tmp_path):
    case = next(case for case in MATRIX['cases'] if case['id'] == 'custom-root')
    document = _document(case)
    secret = 'private-document-value-do-not-log'
    document['sections'][0]['blocks'][0]['type'] = secret
    token = set_request_locale(locale)
    try:
        with pytest.raises(ValueError) as error:
            pandoc_exporter.export_accessible_document(document, tmp_path / 'result.txt', format_name='txt')
        expected = t(MSG_CANONICAL_SCHEMA_FAILED).format(path='/sections/0/blocks/0/type', rule='enum')
        assert str(error.value) == expected
        assert secret not in ''.join(traceback.format_exception(error.value))
    finally:
        reset_request_locale(token)


def test_raw_markdown_is_built_and_validated_before_export(tmp_path):
    output = tmp_path / 'result.txt'
    pandoc_exporter.export_accessible_document('# Title\n\nBody.', output,
        format_name='txt', toolbox=toolbox_config())
    assert output.read_text(encoding='utf-8') == 'Title\nBody.'
