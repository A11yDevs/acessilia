# Core changelog

Brazilian Portuguese: [português brasileiro](CHANGELOG.pt-br.md).

## 0.2.2 — table AST from rows by docstruct

The payload builder and the table backfill build a table AST from rows with
`docstruct.tables.ast.table_ast_from_rows` instead of the core's copy (#470).
On the core's inputs, lists of cells, the two differ only on rows whose cells
are all blank, which docstruct leaves out, returning `None` when none is left. The one input that reaches it is a
table whose text is all whitespace and that has no usable table AST: its
payload block now has `table_ast: None` instead of an AST of one empty cell.
The canonical document's table and the exports are unchanged.

## 0.2.1 — slide box geometry from docstruct

No behaviour change. The slide layout (`manifest/slides.py`) uses docstruct's
box geometry instead of its own copies: `boxes_overlap` and `union_area`, new
in `docstruct.geometry.boxes`, and `docstruct.fusion.similarity.area`. The
core now requires docstruct 0.5.6 or later (#470).

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
