"""Core consumes docstruct's schema with a strict export gate."""

from importlib.resources import files
from pathlib import Path

import pytest
from acessilia_core.export.pandoc_exporter import export_accessible_document
from acessilia_core.pipeline.canonical_builder import build_canonical_document
from docstruct.validation import validate_against_schema
from jsonschema import ValidationError, validate

ROOT = Path(__file__).resolve().parents[3]


def test_root_schema_is_the_byte_identical_generated_package_copy():
    bundled = files('docstruct.schemas').joinpath('accessible_document.schema.json').read_bytes()
    assert (ROOT / 'schemas/accessible_document.schema.json').read_bytes() == bundled


@pytest.mark.parametrize('source', [
    '# Main\n\nBody.\n\n## Child\n\nChild text.\n\n### Leaf\n\nLeaf text.',
    {'pages': [{'blocks': [
        {'type': 'heading', 'level': 1, 'text': 'Main'},
        {'type': 'table', 'rows': [['Name', 'Value'], ['A', '1']]},
        {'type': 'math', 'text': 'x=1'},
    ]}]},
])
def test_core_builder_output_matches_the_packaged_schema(source):
    # An explicit no-op enricher keeps this contract independent of providers.
    document = build_canonical_document(source, title='Document', math_enricher=None)
    validate_against_schema(document, validate)


def test_strict_core_gate_rejects_custom_blocks_while_the_pure_renderer_keeps_its_fallback(tmp_path):
    document = build_canonical_document('# Main\n\nBody.', math_enricher=None)
    document['sections'][0]['blocks'].append({
        'id': 'custom-1', 'type': 'custom', 'text': 'Accepted fallback text',
    })
    with pytest.raises(ValidationError):
        validate_against_schema(document, validate)
    path = tmp_path / 'output.txt'
    with pytest.raises(ValueError, match="/sections/0/blocks/1/type"):
        export_accessible_document(document, path, format_name='txt')
    assert not path.exists()
    from docstruct.export.txt import document_to_txt_lines
    assert "Accepted fallback text" in "\n".join(document_to_txt_lines(document))
