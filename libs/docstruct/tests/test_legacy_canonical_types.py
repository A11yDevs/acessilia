"""E1.3 deprecates legacy dataclasses without changing their public behavior."""

import base64
import inspect
import pickle
import subprocess
import sys
from dataclasses import asdict, fields

import pytest

import docstruct
from docstruct.types import CanonicalBlock, CanonicalDocument, CanonicalSection

# Created with docstruct 0.5.2 at merged #573 (7c6134eb), protocol 4.
# This is a trusted test object, not a pickle supplied by a user.
PRE_DEPRECATION_PICKLE = base64.b64decode(
    'gASVIwEAAAAAAACMD2RvY3N0cnVjdC50eXBlc5SMEUNhbm9uaWNhbERvY3VtZW50lJOUKYGUfZQojAV0aXRsZZSMBkxlZ2FjeZSMCHNlY3Rpb25zlF2UaACMEENhbm9uaWNhbFNlY3Rpb26Uk5QpgZR9lCiMAmlklIwCczGUjAVsZXZlbJRLAWgFjAdTZWN0aW9ulIwGYmxvY2tzlF2UaACMDkNhbm9uaWNhbEJsb2NrlJOUKYGUfZQoaA2MAmIxlIwEdHlwZZSMCXBhcmFncmFwaJSMBHRleHSUjARCb2R5lIwEYmJveJROjApwYWdlX2luZGV4lE6MCG1ldGFkYXRhlH2UdWJhdWJhaB59lIwGc291cmNllIwPcHJlLWRlcHJlY2F0aW9ulHN1Yi4='
)


@pytest.mark.parametrize('cls', [CanonicalDocument, CanonicalSection])
def test_root_reexports_keep_the_original_class_identity(cls):
    assert getattr(docstruct, cls.__name__) is cls
    assert cls.__name__ in docstruct.__all__
    assert cls.__module__ == 'docstruct.types'


@pytest.mark.parametrize('cls', [CanonicalDocument, CanonicalSection])
def test_deprecation_is_documented_and_exposes_migration_metadata(cls):
    for description in (cls.__doc__, cls.__deprecated__):
        assert '0.5.3' in description
        assert 'docstruct.canonical.build_canonical_document' in description
        assert 'docstruct.schemas.accessible_document_schema' in description


@pytest.mark.parametrize('cls,names', [
    (CanonicalDocument, ['title', 'sections', 'metadata']),
    (CanonicalSection, ['id', 'level', 'title', 'blocks']),
])
def test_dataclass_fields_and_constructor_parameters_are_preserved(cls, names):
    assert [field.name for field in fields(cls)] == names
    assert list(inspect.signature(cls).parameters) == names
    assert '__deprecated__' not in cls.__dataclass_fields__


def test_positional_keyword_construction_defaults_and_serialized_state_are_preserved():
    block = CanonicalBlock('b1', 'paragraph', 'Body')
    section = CanonicalSection('s1', 1, None, [block])
    document = CanonicalDocument(title=None, sections=[section])
    assert document.blocks() == [block]
    assert asdict(document) == {
        'title': None,
        'sections': [{'id': 's1', 'level': 1, 'title': None, 'blocks': [{
            'id': 'b1', 'type': 'paragraph', 'text': 'Body', 'bbox': None,
            'page_index': None, 'metadata': {},
        }]}],
        'metadata': {},
    }
    assert '__deprecated__' not in vars(document)
    assert '__deprecated__' not in vars(section)


def test_mutable_defaults_remain_independent():
    first, second = CanonicalDocument('A'), CanonicalDocument('B')
    first.sections.append(CanonicalSection('s1', 1, 'Section'))
    first.metadata['changed'] = True
    assert second.sections == [] and second.metadata == {}
    another = CanonicalSection('s2', 1, 'Other')
    first.sections[0].blocks.append(CanonicalBlock('b1', 'paragraph', 'Body'))
    assert another.blocks == []


def test_pre_deprecation_pickles_still_load_and_current_objects_round_trip():
    document = pickle.loads(PRE_DEPRECATION_PICKLE)
    assert type(document) is CanonicalDocument
    assert type(document.sections[0]) is CanonicalSection
    assert document.title == 'Legacy'
    assert document.metadata == {'source': 'pre-deprecation'}
    assert [block.text for block in document.blocks()] == ['Body']
    assert pickle.loads(pickle.dumps(document)) == document


def test_cold_import_and_construction_emit_no_warnings():
    code = '\n'.join([
        'from docstruct import CanonicalDocument, CanonicalSection',
        'from docstruct.types import CanonicalBlock',
        'section = CanonicalSection("s", 1, "Title", [CanonicalBlock("b", "paragraph", "Body")])',
        'assert CanonicalDocument("Title", [section]).blocks() == section.blocks',
    ])
    result = subprocess.run([
        sys.executable, '-I', '-W', 'error', '-c', code,
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == result.stderr == ''
