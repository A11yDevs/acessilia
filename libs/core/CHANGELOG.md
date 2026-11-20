# Core changelog

Brazilian Portuguese: [português brasileiro](CHANGELOG.pt-br.md).

## 0.2.4 — structural primitives from docstruct 0.5.7

No behaviour change, except one stricter edge case. The core's duplicated
implementations now call `acessilia-docstruct` directly (#612): the table
checks and `DataOutput.table_ast` (`docstruct.tables.structured`), the
heading-hierarchy gap detection and repair (`docstruct.sections`), the
skeleton-order ranking (`docstruct.fusion.skeleton`, same 0.5 threshold), the
slide box helpers (`docstruct.geometry.boxes`), the PNG/JPEG header inspection
(`docstruct.imaging`) and `is_legitimate_text` (`docstruct.fusion.noise`).

The stricter edge case: a `table_ast` whose `rowspan`/`colspan` carries a JSON
boolean used to survive `isinstance(span, int)`; the strict normalizer drops
it. Characterized in `libs/core/tests/test_docstruct_057_adoption.py`.

The core now requires docstruct 0.5.7 or later (#612).

## 0.2.3 — the page judge through the SDK's operation

The `vlm-pairwise-judge` method renders the page and asks the judge through
the SDK's page judge operation (`acessilia_sdk.operations.page_judge`, #470).
The core keeps its decisions: the source check, which pages, the truncation
warning, the threshold and what each failure means. Requests, choices and
failure messages are unchanged, except for one case. An answer whose document
is not an object (null, a list, a string, a number, a boolean) used to raise
`AttributeError` out of the method; it now fails the method as an answer
without a valid `pB`.

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
