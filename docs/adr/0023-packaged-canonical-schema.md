# 0023. Package the canonical schema with an injected validation engine

Brazilian Portuguese: [português brasileiro](0023-packaged-canonical-schema.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-17
- **Components:** docstruct, core
- **Issues:** [#371, E1.2a](https://github.com/A11yDevs/acessilia/issues/371), [#161, D1](https://github.com/A11yDevs/acessilia/issues/161)

## Context

The accessible-document schema lives only in the checkout's `schemas/`, despite
docstruct owning canonical schemas ([ADR 0004](0004-single-source-of-truth-for-contracts.md)).
A consumer of the installed wheel cannot load it. docstruct must keep zero
runtime dependencies. The [approved review](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790)
separates schema packaging and injected validation from a mandatory export gate:
the enum rejects custom block types that existing exports accept.

## Decision

- The normative, byte-unchanged schema is package data at
  `docstruct/schemas/accessible_document.schema.json`. Its draft, identifier and
  constraints remain unchanged. `accessible_document_schema()` reads only this
  fixed installed resource and returns a fresh dictionary; no working-directory
  path, caller file or network is consulted.
- `docstruct.validation.validate_against_schema(document, validator)` receives
  a callable `validator(document, schema)`, compatible with `jsonschema.validate`.
  It must return `None` on success and raise on failure. Exceptions propagate;
  other return values raise `TypeError` rather than silently discarding boolean
  failures or lazy error iterators. Callbacks receive the original document and
  must treat it as read-only. Each call receives its own schema dictionary.
- The runtime imports no validation engine; `jsonschema` is a dev-only
  dependency. Reading bundled package data is the schema accessor's only file
  access; structural algorithms retain their existing purity guarantees.
- **Scoped infrastructure exception (ADR 0017):** the docstruct owner permits
  `schemas/__init__.py:importlib.resources` solely to read this fixed package
  resource when called, never at import time. It accepts no path argument and
  permits no arbitrary files, writes, network or environment access. This is
  required by D1's installed-schema API; generating a second Python schema
  representation would add another artifact to synchronize. The static guard
  allows only this exact module/import pair, and import-time guards still apply.
  **Exit criterion:** remove the exception if the resource accessor is removed
  or replaced by generated embedded data; the unused-exception test enforces
  removal when the import goes away. This ADR's PR review reviews the exception.
- The root `schemas/accessible_document.schema.json` remains a generated,
  byte-identical compatibility copy. `scripts/sync_accessible_document_schema.py`
  regenerates it; its `--check` mode and the core contract test detect drift.
- This additive API ships as docstruct 0.5.2, within the SDK's existing
  `>=0.5,<0.6` range. No external pin or release is changed by this PR.

## Consequences

Installed consumers can use the canonical schema without the repository. Tests
validate library/core builder output, including nested sections, against it.
CI validates the resource from the installed wheel outside the checkout and
keeps the runtime import-purity and export characterization gates.

Existing audit functions and exporters do not call the new opt-in API. Their
accepted inputs and frozen outputs remain unchanged. Enabling strict validation
at the core export gate is E1.2b, a separate compatibility decision and PR;
public-type deprecation and the format catalogue remain separate stages too.
