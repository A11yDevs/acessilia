# Processing manifest model inventory

> A Brazilian Portuguese translation is available in [manifest-model-inventory.pt-br.md](manifest-model-inventory.pt-br.md).

This is the first step of stage 5 of [#203](https://github.com/A11yDevs/acessilia/issues/203). It sorts every class and field of the processing manifest into four domains. That sorting decides what moves to docstruct ([ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.md), decision 1), what stays in the core, and what the Toolbox wraps in its own envelope. It also lists how the two copies of the model differ today. Each difference has to be settled before one shared definition can replace them.

- **Snapshot:** `acessilia` `develop` at `316e49c`, `backend/core/manifest/models.py`; `acessilia-toolbox` `develop` at `85a53dd`, `src/acessilia_toolbox/core/normalization/models.py`.
- **Wire contract:** `urn:a11y-devs:schema:processing-manifest:1.1.0`. The Toolbox also exposes it as `artifact/structured-document@1`. Neither version changes because of this migration ([ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.md), scope of decision 1).

## Domains

| Domain | Meaning | Destination |
|---|---|---|
| **Document** | Elements, structure, hierarchy, location and their invariants | docstruct (pure types and validation) |
| **Origin** | Where the document and its extraction came from: file, extractor run, provider references, confidence | Stays with each component's model; not structural semantics by default |
| **Process** | What the core decided and did: observations, obligations, attempts, statuses | Core |
| **Envelope** | Identity, schema and version of the payload, derived counts, stored artifacts | Core for the manifest; the Toolbox for `artifact/structured-document@1` |

## Classes and fields

| Class | Field(s) | Domain | Notes |
|---|---|---|---|
| `BoundingBox` | all, including `coord_origin` | Document | Already has a pure counterpart in `docstruct.geometry.OrientedBox` (#208). The origin travels with the box. |
| `Provenance` | `page_number`, `bbox` | Document | Location of an element. |
| `Provenance` | `char_start`, `char_end` | Document | Offsets into the element text. |
| `PageDescriptor` | `page_number`, `width`, `height`, `element_ids` | Document | `element_ids` is recomposed after reading order (#209). |
| `ManifestElement` | `id`, `type`, `raw_label`, `reading_order`, `hierarchy_level`, `text`, `parent_id`, `page_number`, `provenance` | Document | `ElementType` is part of the document vocabulary. |
| `ManifestElement` | `source_ref`, `parent_ref` | Origin (hybrid) | Provider references (Docling JSON pointers). They identify an origin, not a structure. `parent_id` is the structural link. |
| `ManifestElement` | `confidence` | Origin (hybrid) | Extractor evidence about the element. Kept on the element, but not a document invariant. |
| `ManifestElement` | `metadata` | Hybrid | An open bag. It holds document facts (`callout_*`, `table_ast`), process marks (`unstructured_page`, `blank_page`) and provider data (`docling_class`). It stays open (`dict`). Its keys are documented per domain before any of them gets a typed field. |
| `SourceDocument` | `filename`, `media_type`, `byte_size`, `sha256` | Origin | Describes the input file. |
| `SourceDocument` | `document_id` | Origin (hybrid) | The document's identity, derived from `sha256`. |
| `SourceDocument` | `path` | Origin | Machine-specific. The golden manifests (#205) replace it. |
| `ExtractorRun` | all | Origin | Execution metadata of the extraction ([ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.md): stays with its component). |
| `Observation` | all, and `Severity` | Process | Core findings. Messages come from the core's i18n catalog. |
| `Obligation`, `ObligationAttempt` | all, with the statuses | Process | Planning policy, owned by the core. The Toolbox keeps the field only for 1.1.0 compatibility and always leaves it empty. |
| `Artifact` | all | Envelope | Files the core produced for a run. |
| `ManifestSummary` | `page_count`, `element_count`, `element_types` | Envelope (derived from the document) | Counts validated against the lists. |
| `ManifestSummary` | `observation_count`, `obligation_count` | Envelope (derived from the process) | Counts validated against the lists. |
| `ProcessingManifest` | `$schema` (`schema_ref`), `schema_version`, `manifest_id`, `revision`, `created_at` | Envelope | `$schema` is an alias; `populate_by_name=True`. |
| `ProcessingManifest` | `status` | Process | Lifecycle of the core's run. |
| `ProcessingManifest` | `title`, `language` | Document | Document properties. |
| `ProcessingManifest` | `pages`, `elements` | Document | The document itself. |
| `ProcessingManifest` | `observations`, `obligations` | Process | |
| `ProcessingManifest` | `artifacts`, `summary` | Envelope | |

### Invariants

| Invariant | Domain | Core | Toolbox |
|---|---|---|---|
| Unique element ids | Document | yes | **no** |
| `parent_id` exists, is not the element itself, and the hierarchy has no cycle | Document | yes | **no** |
| Unique page numbers | Document | yes | yes |
| `page.element_ids` reference known elements | Document | yes | yes |
| Extraction ends after it starts | Origin | yes | **no** |
| Unique observation, obligation and artifact ids | Process, envelope | yes | **no** |
| Targets, dependencies and attempt artifacts exist; dependencies have no cycle; a satisfied obligation has satisfied predecessors | Process | yes | yes |
| `method_costs` only for admissible methods | Process | always | only when both lists are non-empty |
| Method costs are not negative | Process | yes | **no** |
| Attempt ends after it starts | Process | yes | yes |
| `summary` counts match the lists | Envelope | yes | yes |

## Differences between the two copies

Both copies declare the same `$id`. Today they publish different schemas and accept different payloads:

1. **Published JSON Schema text.** The `description` differs. The core has a Portuguese description; the Toolbox has an English one, marked "verbatim: part of the published 1.1.0 schema". The Toolbox also adds `"deprecated": true` to `obligations`. One `$id` should name one schema.
2. **The Toolbox accepts payloads the core rejects.** Its copy lacks the invariants marked **no** above. A Toolbox payload with a duplicate element id, a dangling or cyclic `parent_id`, or an inverted extractor interval passes there and fails in `ProcessingManifest.model_validate` in the core.
3. **Validation messages.** The core's are in Portuguese (one goes through i18n); the Toolbox's are in English. Messages are not part of the wire contract.

## Consequences for the next steps of stage 5

- **docstruct receives:** the document rows above as standard-library types, with the document invariants as a pure validation function that returns findings, not exceptions. This follows `docstruct.validation`. No Pydantic, no I/O.
- **The core keeps:** `ProcessingManifest` as the envelope and the process models with their validators. Its Pydantic models for the document part become adapters checked against docstruct, then derived from it. Every step is checked against the golden manifests and the round trip of #205.
- **The Toolbox keeps:** its envelope and `artifact/structured-document@1`. Its document part converges on the same docstruct definition when it moves to docstruct 0.4.0 ([ADR-0004](../adr/0004-single-source-of-truth-for-contracts.md)).
- **Decide first (D1):** how the JSON Schema of the document part is produced from docstruct (generated, or verified mechanically), and which `description` and `deprecated` marks the single 1.1.0 schema keeps.
- **Decide first:** whether the Toolbox adopts the missing invariants within 1.1.0. They tighten validation, so some payloads that validate today would no longer validate. The alternative is to keep them core-only until a new schema version.

## Outcome (2026-10-20)

The decisions were taken on [#203](https://github.com/A11yDevs/acessilia/issues/203) and carried out:

- **D1:** `docstruct.manifest` (docstruct 0.4.0) is the normative source of the document part. The wire schema is not generated from it. Each repository's contract test checks it against `docstruct.manifest.field_specs` instead: `tests/test_manifest_semantic_contract.py` in the core, `tests/unit/test_structured_document_contract.py` in the Toolbox.
- **One schema:** both components publish the identical 1.1.0 schema. The `description` is the text first published (see `schemas/processing_manifest.schema.json`), and `obligations` has no `deprecated` mark.
- **The same invariants:** both validate the document part through `docstruct.manifest.document_invariant_findings`. The Toolbox adopted the process invariants it lacked. This was treated as a conformance fix of 1.1.0: none of the 31 real payloads checked (historical manifests and recorded snapshots) was rejected, so no new schema version was needed.
- **Differences 1 and 2 above are resolved.** Difference 3 remains by design: the core resolves messages through its i18n catalog, and the Toolbox keeps English messages.
