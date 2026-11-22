# Core changelog

Brazilian Portuguese: [português brasileiro](CHANGELOG.pt-br.md).

## 0.3.2 — formula_tools docstruct re-exports deprecated

No behaviour change for migrated callers; the old names now emit a
`DeprecationWarning`. `acessilia_core.formula_tools` keeps `wrap_latex` and
`label_spoken_formula`. Import the replacements directly from
`docstruct.text.latex`: `bare_latex` for `normalize_latex` and
`ensure_math_delimiters` for the name of the same name. In-repository consumers
were migrated, and the compatibility names stay until a later breaking version
removes them (#656).

## 0.3.1 — docstruct re-exports deprecated in the pipeline bridges

No behaviour change. `acessilia_core.pipeline.table_ast` and
`acessilia_core.pipeline.validators` keep their localized functions, but the
pure docstruct functions and msgids they used to re-export now emit a
`DeprecationWarning`; import them from `docstruct.tables.ast` and
`docstruct.validation` instead. In-repository consumers were migrated, and the
compatibility names stay until a later breaking version removes them (#656).

## 0.3.0 — the Toolbox adapter no longer re-exports the SDK

**Breaking change** for callers that imported SDK names from
`acessilia_core.toolbox.toolbox_client`. Import `PROVIDER_DEFAULTS`, the
`Toolbox*` errors, `ToolboxCapabilityClient`, `auth_headers`,
`execute_capability` and `require_capability` from `acessilia_sdk.toolbox`
instead.

Runtime behaviour is unchanged. The Core adapter now only maps the run's
`ToolboxConfig` to the SDK client configuration and builds clients, so the
Core no longer acts as an SDK facade (#656).

## 0.2.6 — i18n infrastructure through the SDK

No behaviour change. The generic i18n infrastructure now lives in
`acessilia_sdk.i18n` (#712): locale parsing and normalization, negotiation,
per-task request context, catalog compilation and gettext/plural lookup. The
core keeps its catalogs, message ids, locale policies and the public `t()`/`n()`
translation API. The temporary `acessilia_core.i18n.parse_locales` facade is
removed; the existing `set_request_locale`/`reset_request_locale` names remain
as compatibility re-exports, and new code should import them from the SDK. The
core now requires `acessilia-sdk>=0.4,<0.5`. The new floor also covers the SDK
APIs Core 0.2.5 already consumed -- dual-provider fusion, downscale/renderable
check and `run_sync` -- which the SDK publishes in 0.4.0; the 0.2.5 metadata
still pointed at 0.3.x.

## 0.2.5 — dual-provider fusion, downscale, render check and sync bridge via SDK and docstruct

No behaviour change, except two minor edge cases noted below. The core now
delegates its dual-provider extraction, pure payload fusion/page routing, image
downscaling, renderable-media pre-check, and sync/async bridges to
`acessilia-sdk` and `acessilia-docstruct` (#612):

- `pipeline/fusion.py`: `extract_fused` delegates to
  `acessilia_sdk.operations.fusion.extract_dual_fused` (preserving per-provider
  failure and artifact-fallback logging via `DualFusionUnavailable`), while
  `fuse_extraction_payloads` and `apply_page_routes` delegate to
  `docstruct.fusion.payload.fuse_extraction_payloads` and `route_pages`
  (preserving routed and missing-page logs).
- `toolbox/vision_payload.py`: `downscale_image` delegates rendering to
  `acessilia_sdk.toolbox.clients.pdf.downscale_image`, keeping `ToolboxConfig`
  client lifecycle, localized warning log, and `None` recovery in the core.
- `pipeline/toolbox.py` and `pipeline/judge.py`: replace `_check_renderable`
  with `acessilia_sdk.toolbox.clients.pdf.check_renderable`.
- `pipeline/handlers/inspection.py` and `pipeline/handlers/fusion.py`: replace
  duplicated thread-pool sync/async bridges with `acessilia_sdk.runtime.run_sync`.

Minor edge-case changes:

- The media-type mismatch `ValueError` raised by `check_renderable` now says
  `Source is <declared> but would be sent as <extension>` (dropping
  `"in the manifest"`).
- `vision_payload.downscale_image` with a non-positive or non-finite `scale`
  now returns `None` without constructing a Toolbox client instead of rendering
  a 1 px image.

The core now requires `acessilia-docstruct>=0.5.8,<0.6` (#612).

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
