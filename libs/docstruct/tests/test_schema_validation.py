"""The bundled canonical schema works with an explicit, consumer-owned engine."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError, validate

from docstruct.canonical import build_canonical_document
from docstruct.schemas import accessible_document_schema
from docstruct.validation import validate_against_schema


def document():
    return build_canonical_document(
        '# Main\n\nBody.\n\n## Child\n\nChild text.\n\n### Leaf\n\nLeaf text.',
        title='Document', language='en-US',
    )


def test_schema_is_a_valid_draft_2020_12_definition():
    schema = accessible_document_schema()
    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['$id'] == 'urn:a11y-devs:schema:accessible-document:1.0.0'
    Draft202012Validator.check_schema(schema)


def test_package_resource_does_not_depend_on_the_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    validate_against_schema(document(), validate)


def test_each_schema_load_returns_fresh_nested_data():
    schema = accessible_document_schema()
    schema['$defs']['block']['properties']['type']['enum'].clear()
    assert len(accessible_document_schema()['$defs']['block']['properties']['type']['enum']) == 11


def test_validator_receives_original_input_and_a_private_schema_copy():
    source = object()
    calls = []

    def engine(instance, schema):
        assert instance is source
        calls.append(deepcopy(schema))
        schema.clear()

    assert validate_against_schema(source, engine) is None
    assert calls == [accessible_document_schema()]


@pytest.mark.parametrize('error', [RuntimeError('invalid'), ImportError('engine unavailable')])
def test_injected_errors_propagate_without_fallback(error):
    def engine(instance, schema):
        raise error

    with pytest.raises(type(error)) as caught:
        validate_against_schema(document(), engine)
    assert caught.value is error


@pytest.mark.parametrize('result', [False, True, [], {}, iter(())])
def test_non_none_validator_results_are_not_silently_accepted(result):
    with pytest.raises(TypeError, match='return None on success and raise on failure'):
        validate_against_schema(document(), lambda instance, schema: result)


@pytest.mark.parametrize('source', [None, [], {}])
def test_schema_rejects_invalid_root_values(source):
    with pytest.raises(ValidationError):
        validate_against_schema(source, validate)


@pytest.mark.parametrize('field,value', [('type', 'custom'), ('level', 7)])
def test_local_refs_validate_grandchildren_and_preserve_error_paths(field, value):
    source = document()
    leaf = source['sections'][0]['children'][0]['children'][0]
    leaf['blocks'][0][field] = value
    before = deepcopy(source)
    with pytest.raises(ValidationError) as caught:
        validate_against_schema(source, validate)
    assert list(caught.value.absolute_path) == [
        'sections', 0, 'children', 0, 'children', 0, 'blocks', 0, field,
    ]
    assert source == before


@pytest.mark.parametrize('source', [
    '',
    'Body before any heading.',
    '# Main\n\nBody.\n\n## Child\n\nChild text.\n\n### Leaf\n\nLeaf text.',
    {'pages': [{'blocks': [
        {'type': 'heading', 'text': 'Main', 'level': 1},
        {'type': 'paragraph', 'text': 'Body'},
        {'type': 'list', 'ordered': True, 'items': ['First', 'Second']},
        {'type': 'table', 'rows': [['Name', 'Value'], ['A', '1']]},
        {'type': 'image', 'alt_text': 'An image'},
        {'type': 'code', 'text': 'print(1)', 'language': 'python'},
        {'type': 'math', 'text': 'x=1'},
        {'type': 'quote', 'text': 'Quoted text'},
        {'type': 'details', 'text': 'Details'},
        {'type': 'note', 'text': 'Note'},
        {'type': 'warning', 'text': 'Warning'},
    ]}]},
    {'pages': [{'page_number': 1, 'blocks': [], 'text': ''}], 'page_count': 1},
])
def test_pure_builder_output_conforms_without_enabling_runtime_validation(source):
    before = deepcopy(source)
    built = build_canonical_document(source, title='Document', language='en-US')
    before_validation = deepcopy(built)
    assert validate_against_schema(built, validate) is None
    assert built == before_validation and source == before


def test_builder_contract_includes_multiple_nested_sections():
    source = document()
    assert source['sections'][0]['children'][0]['children'][0]['title'] == 'Leaf'
    validate_against_schema(source, validate)
