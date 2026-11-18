# 0026. Validate the canonical schema at the Core export gate

Brazilian Portuguese: [português brasileiro](0026-strict-canonical-export-gate.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-18
- **Components:** Core, docstruct
- **Issues:** [#371, E1.2b](https://github.com/A11yDevs/acessilia/issues/371), [#161, D1](https://github.com/A11yDevs/acessilia/issues/161)

## Context

ADR [0023](0023-packaged-canonical-schema.md) packaged the schema and its injected
validation API without changing exports. The [approved review](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790)
requires a separate compatibility decision before mandatory activation: the
existing audit accepts custom block types and other schema-invalid values.
The neutral stages ended with PR #576; this is a validation behavior change.

The compatibility corpus records 17 cases at `9845d84d`, before this gate:
15 export successfully and two fail the audit, across TXT, HTML, DOCX and
PDF/UA (remote renderers mocked). Of those 15, twelve normalized documents
violate the schema: custom types at the root/in children/in filtered content,
missing block or section IDs, invalid verbosity/audience/document-ID types,
empty document title, short language and invalid child level. Three remain
accepted: a valid nested document, metadata extensions and numeric table cells
that the existing sanitizer already converts to text.

## Decision

- Core 0.2.0 makes schema validation mandatory in `export_accessible_document`,
  shared by public TXT/HTML/DOCX/PDF/UA exports. It uses docstruct's
  `validate_against_schema(document, validator)` with `jsonschema.validate`
  injected by Core, using the packaged, unchanged schema. No dev dependency is
  promoted into docstruct's runtime.
- Order is **existing normalization → existing structural/accessibility audit
  → strict schema validation → profile selection/check → AST/renderer**.
  Existing audit blockers keep precedence. Validate the entire normalized
  document, including sections/children and blocks that a format would filter;
  an export profile cannot hide a malformed canonical block.
- This gate adds no normalization, schema constraint, new flag, fallback or
  bypass. Raw text/Markdown still goes through the builder; dictionaries still
  go through the existing sanitizer. Malformed input can still fail in those
  earlier steps. Existing numeric-table normalization and metadata extensions
  stay accepted. "Strict" means enforcing the schema's actual constraints:
  additional fields and schema-version strings are not restricted further.
- A new schema failure raises localized `ValueError`, naming the JSON Pointer
  and schema keyword. Do not include document values or jsonschema's verbose
  exception in the diagnostic/traceback. Reject before AST construction,
  directory creation, local serialization or a remote renderer call. Existing
  destination files remain untouched. The worker's required TXT failure path
  records the job error, cleans its output and registers no download token.
- This intentionally narrows accepted public inputs, so the pre-1.0 Core moves
  from **0.1.1 to 0.2.0**. Callers must supply canonical mappings matching the
  packaged schema; use the builder for document/section IDs and shape, repair
  invalid fields, and represent extension semantics with a supported block
  type plus metadata. No content is silently discarded to obtain compliance.
- Pure docstruct serializers retain their public fallback behavior and E1.0
  goldens. Internal benchmark Markdown bypasses the Core gate as before. Audio
  and ZIP consume the worker's already validated outputs. The schema, SDK
  contracts, profile policy and export suffixes remain unchanged. This ADR
  implements the separate activation anticipated by ADR 0023; its packaging
  and purity decisions remain in force.

## Consequences

Previously accepted invalid canonical mappings now fail exports, including
persisted/cached mappings used by resumed jobs. Existing artifact downloads
are not revalidated. This PR's
review approves that compatibility change; it is not a neutral refactor or a
release publication. The changelog and bilingual compatibility corpus explain
migration. Schema conformance complements the audit: duplicate IDs and empty
sections still fail even when the JSON Schema itself would permit them.

Tests cover the 68 old/new format outcomes, nested and filtered content,
normalization, exact retained TXT output, input immutability, output preservation,
no renderer side effects, localized bounded diagnostics and worker failure.
Existing package isolation, builder/schema and pure-export parity gates remain.
The optional six-document dataset is absent in this checkout; it supplies no
claimed evidence and creates no skipped test.
