# 0024. Deprecate legacy canonical dataclasses while retaining compatibility

Brazilian Portuguese: [português brasileiro](0024-legacy-canonical-type-deprecation.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-17
- **Components:** docstruct
- **Issue:** [#371, E1.3](https://github.com/A11yDevs/acessilia/issues/371)

## Context

`CanonicalDocument` and `CanonicalSection` are public dataclasses exported from
both `docstruct.types` and `docstruct`. They describe an older, smaller model:
the document lacks schema version/id/language, and the section has no children.
The core and SDK use the dictionaries built by `docstruct.canonical`, whose
serialized contract belongs to the packaged JSON Schema (ADR [0023](0023-packaged-canonical-schema.md)),
rather than these dataclasses. Other wheel consumers may still use the names
or persisted objects. Removing or replacing them would break that public API.

## Decision

- Deprecate only these two legacy dataclasses, starting with docstruct **0.5.3**.
  Their docstrings and informational `__deprecated__` class strings identify
  the version and migration APIs. The root reexports and documentation mark
  their compatibility status explicitly.
- Preserve the original classes, module paths, root exports, constructors,
  fields/defaults, positional arguments, equality, `asdict`, `blocks()` and
  pickling behavior. The marker is an unannotated class attribute, not a
  dataclass field or instance state. No wrapper, alias or schema-model rewrite
  is introduced.
- Imports and construction stay silent. Deprecation is documentation and
  introspection metadata; tools may inspect the marker explicitly. No warning
  emission or automatic static-tool diagnostic is part of this contract. This
  keeps the stage within #371's parity and docstruct's purity requirements.
- New document/section code uses dictionaries returned by
  `build_canonical_document` and the structure described by
  `accessible_document_schema`. `asdict` of a legacy object does not supply the
  schema's missing fields and is not an automatic migration.
- `CanonicalBlock`, `BBox` and the other algorithm value objects remain active.
  The 0.5.x line retains the deprecated names; removal requires a separate
  breaking-version decision and consumer migration under the release policy.
  No removal release is scheduled here.

## Consequences

Consumers get a migration direction without changing existing execution or
serialization. External users must read the documentation or inspect metadata;
they receive no new runtime warning. The patch version records this compatible
status change and stays within the SDK's existing `>=0.5,<0.6` range.

Compatibility tests preserve the original class identities, constructor fields,
defaults and serialized state, load a pickle generated with 0.5.2 and import and
construct objects with warnings treated as errors. Existing purity, isolated
wheel and export characterization gates still apply. No runtime dependency,
schema, export policy, external pin or release publication changes here.
