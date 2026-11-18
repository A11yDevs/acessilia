# Core changelog

Brazilian Portuguese: [português brasileiro](CHANGELOG.pt-br.md).

## 0.2.0 — strict canonical export validation

**Breaking validation change:** TXT, HTML, DOCX and PDF/UA now require the full
normalized canonical document to match docstruct's packaged schema after the
existing audit and before profile selection. Previously accepted custom block
types, missing block/section IDs and invalid field values now raise localized
`ValueError` before rendering. Existing audit failures retain precedence.

Before adopting 0.2.0, build document trees with `docstruct.canonical` or supply
all required IDs/fields. Repair invalid values; represent custom semantics with
one of the eleven supported block types and metadata. Passing a custom block
in a level filtered by TXT does not bypass the gate. Numeric table cells still
receive the existing sanitizer's text conversion; metadata extensions remain
valid. Raw text/Markdown still goes through the builder.

Persisted/cached canonical mappings, including resumed jobs, are checked again
when exported. Existing artifacts and download tokens are not revalidated.

Pure docstruct serializers and their fallback behavior, the schema, SDK
contracts, profiles, filenames and legacy downloads remain unchanged. No
strictness flag or fallback is added. See [ADR 0026](../../docs/adr/0026-strict-canonical-export-gate.md)
and the [compatibility corpus](../../tests/fixtures/export_schema_gate/README.md).
