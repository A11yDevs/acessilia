# SDK result bindings: consumed schemas and migration scope

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](sdk-result-bindings.pt-br.md).

This is the inventory step requested by the [latest review of #213][review],
under #380. It defines the proposed scope of the next two implementation PRs;
it does not introduce result models or change clients. The issue stays open
until the selected bindings are generated, used and checked for drift.

## Evidence and ownership

The inventory compares core/SDK `develop` at
`2d5e885e5fb57ea0d94835ef124c3ddcec741129` with the Toolbox's published
[contract][contract], [schema directory][schemas] and [OpenAPI][openapi] at
**`c536c2007912e0ce2f20bd930215d96e6f4c09be`**. Those immutable links identify
the evidence, not a promise about a later Toolbox deployment. Generation must
read published contracts and schemas; it must not import Toolbox Python code
or infer schemas from `capabilities/*.yaml`.

This refresh replaces the pre-publication `77c7df7` evidence. Toolbox
[#160][dataset-publication] and [#161][layout-publication] are merged, and
[#158][dataset-followup] and [#159][layout-followup] are closed. Dataset and
layout outputs below are published contracts, with explicit PR-2/PR-3 work
rather than missing-contract dependencies.

The [SDK allowlist](../libs/sdk/src/acessilia_sdk/toolbox/capabilities.py)
selects **28 capability versions: 18 execute and 10 REST**. All appear below.
Its allowed ids, selected exact versions, transports, provider keys/defaults
and error labels remain SDK choices. The generated registry block currently
contains only the published `output_schema` and `idempotent` projection;
REST entries deliberately retain `output_schema=None`. A contract refresh
must not automatically authorize another capability.

The [generator](../scripts/generate_sdk_bindings.py) and
[capture script](../scripts/capture_toolbox_contract.py) currently select only
`reference@1.json`. `ArtifactReference` is the only generated result model.
The normalized local contract fixture omits `schema_refs`, `dataset_routes`,
inputs and most execution metadata; its comment names `develop`, not an immutable SHA. The
publication classifications below therefore come from the pinned public
contract, rather than being inferred from that fixture or its registry.

Under [ADR-0002](adr/0002-component-responsibilities.md) and
[ADR-0004](adr/0004-single-source-of-truth-for-contracts.md), Toolbox owns
operational wire contracts; SDK derives selected client bindings; docstruct
owns canonical structure and geometry; core interprets results and decides
policy. New model generation must preserve those boundaries.

## Execute outputs

The schema column names the `artifact/…` output reference, with that prefix
omitted. These references normally describe **`ExecutionResponse.document`**,
not the enclosing response, its provenance or downloaded binary bytes.

SDK client links below are relative to
[`acessilia_sdk.toolbox.clients`](../libs/sdk/src/acessilia_sdk/toolbox/clients).
“Selected” is the proposed PR-2 set. “Deferred” means published but outside
that initial set: an SDK/CLI raw pass-through API exists, but no current core
reader justifies generating its whole result family in this change.

| Selected capability | Published output reference | Reader and current return shape | Classification / next action |
|---|---|---|---|
| `document.structure.extract@1` | `structured-document@1` | [structure client](../libs/sdk/src/acessilia_sdk/toolbox/clients/structure.py) returns an envelope; [core extraction](../libs/core/src/acessilia_core/manifest/toolbox_extractor.py), [fusion](../libs/core/src/acessilia_core/pipeline/fusion.py) and [benchmark](../scripts/bench/toolbox.py) read it | **Reuse docstruct**, including `StructuredDocument` and payload adapters; do not generate another canonical manifest/element model |
| `document.layout.analyze@1` | `layout-analysis@1` | [layout client](../libs/sdk/src/acessilia_sdk/toolbox/clients/layout.py) returns an envelope; existing helpers tolerate page lists/maps but do not extract MinerU classifications | **Published, selected for PR 2**: a variant-aware SDK binding; generated operational definitions plus reused docstruct for the manifest branch, as detailed below |
| `math.recognize@1` | `latex@1` | [math client](../libs/sdk/src/acessilia_sdk/toolbox/clients/math.py), `recognized_formulas`, [formula operations](../libs/sdk/src/acessilia_sdk/operations/formula.py), [core math binding](../libs/core/src/acessilia_core/toolbox/toolbox_math_tools.py) | **Selected**: `LatexResult`; preserve the legacy formula-list adapter as well as single-expression results |
| `math.convert@1` | `mathml@1` | Math client returns an envelope; formula operations and core bindings read `mathml` or `latex`, according to direction | **Selected**: `MathmlResult`; characterize both conversion directions and missing-text behavior first |
| `math.verbalize@1` | `verbalized@1` | Math client returns an envelope; formula operations and core bindings read `verbalized` | **Selected**: `VerbalizedResult` |
| `document.adjudicate.page@1` | `page-judgement@1` | [adjudication client](../libs/sdk/src/acessilia_sdk/toolbox/clients/adjudicate.py), `page_judgement_probability`, [core judge](../libs/core/src/acessilia_core/pipeline/judge.py) | **Selected**: `PageJudgement`; retain the probability adapter's existing coercion/failure behavior |
| `document.adjudicate.region@1` | `region-transcription@1` | Adjudication client's `transcribe_region` returns an envelope containing `text`/`model` | **Selected**: `RegionTranscription`, the small companion result of the same SDK client |
| `pdf.validate.pdf_ua@1` | `pdf-validation-report@1` | [validation client](../libs/sdk/src/acessilia_sdk/toolbox/clients/pdf_validate.py) returns the document; [core audit](../libs/core/src/acessilia_core/toolbox/pdf_ua_audit.py) reads compliance, failures and counts | **Selected**: `PdfValidationReport`; non-compliance remains a successful report |
| `media.inspect@1` | `media-inspection@1` | [media client](../libs/sdk/src/acessilia_sdk/toolbox/clients/media_inspect.py) returns the document; [core binding](../libs/core/src/acessilia_core/toolbox/media_inspect.py) reads dimensions, nature, count and visual-inspection flag | **Selected**: `MediaInspection`; distinguish unknown/null measurements from measured values |
| `pdf.render@2` | `image@2` | [PDF client](../libs/sdk/src/acessilia_sdk/toolbox/clients/pdf.py) returns SDK-owned `RenderedPage(image, clip, document)`; [core render binding](../libs/core/src/acessilia_core/pipeline/toolbox.py) and formula operations read it | **Selected**: `RenderedPageMetadata` for the document only; preserve verified PNG retrieval and applied-clip checks |
| `document.text.spans@1` | `text-spans@1` | PDF client's `text_spans` returns the document, `text_spans_by_page` indexes it; [core binding](../libs/core/src/acessilia_core/toolbox/text_spans.py) feeds inline-math readers | **Selected**: `TextSpansResult`; preserve page batching, coordinates and span validation |
| `document.ocr@1` | `ocr-result@1` | [OCR client](../libs/sdk/src/acessilia_sdk/toolbox/clients/ocr.py) returns the envelope; SDK/CLI expose it | **Published, deferred**: nested OCR items and fixed-size boxes |
| `document.ocr.page@1` | `page-transcription@1` | [page OCR client](../libs/sdk/src/acessilia_sdk/toolbox/clients/page_ocr.py) returns the envelope; SDK/CLI expose it | **Published, deferred**: a flat schema already expressible by the current generator |
| `image.page.orient@1` | `page-orientation@1` | [orientation client](../libs/sdk/src/acessilia_sdk/toolbox/clients/orientation.py) returns the envelope; SDK/CLI expose it | **Published, deferred**: numeric enum, bounds and nullable dimensions |
| `table.recognize@1` | `table-candidates@1` | [table client](../libs/sdk/src/acessilia_sdk/toolbox/clients/table.py) returns the envelope; SDK/CLI expose greedy/sample generations | **Published, deferred**: local references and generation arrays; these operational candidates are not docstruct's canonical table AST |
| `pdf.split@1` | `page-collection@1` | PDF client's `split` returns the envelope with page images; SDK/CLI expose it | **Published, deferred**: arrays of nested page metadata/base64 payloads |
| `document.export.pdf_ua@1` | `pdf-export@1` | [export base](../libs/sdk/src/acessilia_sdk/toolbox/clients/pandoc_export.py) verifies/downloads the artifact and returns the envelope; [core exporter](../libs/core/src/acessilia_core/export/pandoc_exporter.py) calls it | **Published, deferred**: existing artifact checks cover the currently read fields; metadata generation can follow separately |
| `document.export.docx@1` | `docx-export@1` | Same export base, configured by the [DOCX client](../libs/sdk/src/acessilia_sdk/toolbox/clients/docx.py) | **Published, deferred**: same bounded metadata family as PDF export |

`structured-document@1.json` identifies itself as
`processing-manifest:1.1.0`. Its structural fields belong to
[`docstruct.manifest`](../libs/docstruct/src/docstruct/manifest.py), while
origin/process state stay with their producers. The existing
[core document adapter](../libs/core/src/acessilia_core/manifest/document_adapter.py) and
[semantic contract tests](../tests/test_manifest_semantic_contract.py) already
exercise that boundary. Reusing it does not require making the SDK depend on
core Pydantic models or generating docstruct's model from a Toolbox schema.

### Layout binding in PR 2

The published [layout contract][layout-contract] is a Draft 2020-12
`anyOf`/`allOf` union. Docling emits compact `pages`/`page_count`/`region_count`;
MinerU emits a processing manifest with required
`extractor.configuration.layout_regions`, `region_count` and `backend`.
Both publish page arrays. The current generator rejects the union; merely
adding its filename to `MODELS` cannot produce a correct binding.

PR 2 includes this binding alongside the nine selected generated execute
models, with this bounded plan:

1. Capture the complete published `layout-analysis@1.json`. Extend the
   SDK-owned model selection to identify explicit local `$defs` targets:
   `LayoutPages` and its nested operational records, and
   `MineruLayoutConfiguration` and its classification records. Generate those
   operational shapes from the captured definitions, not from provider code.
2. Use an SDK adapter for the two known representations. Reuse
   `docstruct.manifest` payload adapters, `StructuredDocument` and canonical
   geometry for the manifest's document fields; retain producer fields and
   layout metadata separately. Do not generate the embedded `ProcessingManifest`
   or its canonical page/element/box definitions as SDK models.
3. Reach that adapter through additive typed layout readers/accessors. Preserve
   the current raw envelope and legacy page-map compatibility of existing
   helpers. Characterize both providers, empty results, required metadata and
   unresolved origins; metadata page indexes are zero-based, canonical page
   numbers are one-based, and MinerU does not supply classification confidence.
4. Keep general union/intersection compilation unsupported. The explicit
   layout adapter is tested against the complete published union, including
   rejection of generic manifests without layout metadata. Selecting a known
   definition must not silently drop constraints from its containing branch.

This is a selected layout binding, not a tenth generated canonical manifest.
Any branch that cannot meet these checks must be reported as incomplete in
PR 2 rather than silently flattened or declared covered.

## REST outputs

These are dedicated routes: there is **no execute envelope** to unwrap. The
declared capability reference alone is insufficient to assign a Python model
to a REST response. The pinned contract's `dataset_routes` and OpenAPI's
`x-toolbox-dataset-binding` now publish the exact method/path/capability/version
and response schema for all eight dataset routes. Use that route schema for
REST; use capability output metadata for execute results. The schema column
below shows both references where they differ. Published
[dataset contract documentation][dataset-contract] and provider/REST/MCP
[conformance examples][dataset-examples] accompany the schemas.

| Selected capability | Capability output / precise REST schema | Dedicated route / SDK result | Classification / next action |
|---|---|---|---|
| `artifact.store@1` | `reference@1` | `POST /v1/artifacts`; [artifact client](../libs/sdk/src/acessilia_sdk/toolbox/clients/artifact.py): `upload_reference` returns `ArtifactReference`, `upload` returns the id | **Generated now**; preserve `upload` compatibility with older stored-record responses |
| `artifact.retrieve@1` | `binary@1` | `GET /v1/artifacts/{id}`; verified bytes or download through the artifact client | **Descriptor**; no JSON result model for bytes |
| `dataset.list@1` | `dataset-list@1` | `GET /v1/datasets`; [dataset client](../libs/sdk/src/acessilia_sdk/toolbox/clients/dataset.py) returns a list | **Published, selected for PR 3**: `list[DatasetInfo]`; generate the collection reader from the array schema |
| `dataset.describe@1` | `dataset-info@1` | `GET /v1/datasets/{id}`; returns an object | **Published, selected for PR 3**: `DatasetInfo`; verify the route binding and real response examples |
| `dataset.list_splits@1` | `dataset-splits@1` | `GET /v1/datasets/{id}/splits`; returns a list of split objects | **Published, selected for PR 3**: `list[SplitInfo]` |
| `dataset.list_items@1` | `dataset-item-list@1` → `dataset-item-summary-list@1` | `GET /v1/datasets/{id}/splits/{split}/items`; paged list of summaries; `list_all_items` aggregates pages | **Published, selected for PR 3**: `list[ItemSummary]`; preserve pagination and summary fields |
| `dataset.get_item@1` | `dataset-item@1` | `GET /v1/datasets/{id}/splits/{split}/items/{item}`; full item object | **Published, selected for PR 3**: `DatasetItem`; preserve open metadata and artifact/annotation references |
| `dataset.get_artifact@1` | `binary@1` | `GET /v1/datasets/{id}/splits/{split}/items/{item}/artifacts/{path}`; bytes | **Descriptor**; preserve path encoding and raw bytes |
| `dataset.sample@1` | `dataset-item-list@1` → `dataset-sample@1` | `GET /v1/datasets/{id}/splits/{split}/sample`; list of full items | **Published, selected for PR 3**: `list[DatasetItem]`; keep full items distinct from listing summaries |
| `dataset.sync@1` | `dataset-sync-report@1` | `POST /v1/datasets/{id}/sync`; SDK currently forwards any JSON | **Published, selected for PR 3**: `list[DatasetSyncEntry]`; the normative result is an array, including skipped events and empty results |

The dataset contract prerequisite [Toolbox #158][dataset-followup] was
completed by [#160][dataset-publication]. PR 3 now selects six record bindings:
`DatasetInfo`, `SplitInfo`, `ItemSummary`, `DatasetItem`, `DatasetArtifactRef`
and `DatasetSyncEntry`, from their corresponding published object schemas.
It also selects five top-level array bindings/readers: `dataset-list@1`,
`dataset-splits@1`, `dataset-item-summary-list@1`, `dataset-sample@1` and
`dataset-sync-report@1`. Keep arrays as arrays, including `[]`; no envelope
or aggregate sync object is introduced.

The shared execute family `dataset-item-list@1` accepts summaries or full
items. Capture it for the capability/route cross-check, but do not use it to
generate either dedicated REST reader or add general union compilation.
Record schemas embedded in collections must agree with their published source
objects. Provider/reference work in Toolbox #141 remains separate.
The SDK [CLI](../libs/sdk/src/acessilia_sdk/cli.py)
uses all eight routes; [benchmark helpers](../scripts/bench/toolbox.py) read
item summaries, full items and artifact bytes.

The local `DatasetArtifactRef` definition in `dataset-item@1` describes a
dataset path with optional metadata. It is not `artifact/reference@1`, which
requires a digest and store. Likewise, a render/export document carrying an
`artifact_id` is not automatically an `ArtifactReference`. Reuse a type only
when the published shapes and semantics actually agree.

## Required generator work, limited to selected results

Proposed class/reader names are SDK bindings, not a new source of contract
truth. PR 2 selects the **nine execute result models plus the layout binding**
described above. PR 3 selects the **six dataset record models and five precise
REST array bindings**, with the shared execute family captured only for
cross-checking. Extend `MODELS`/`SDK_MODEL_SCHEMAS` and explicit definition
selection in those PRs after validating consumers and compatibility. No
generator, model selection or captured fixture is changed by this inventory.

The current generator was exercised against all 26 distinct published
execute/REST JSON schema files in the inventory (excluding the already-generated reference).
Only `verbalized@1`, `region-transcription@1` and the deferred
`page-transcription@1` currently render successfully. The others fail with
`BindingError`; the first rejected keyword is not necessarily the only
unsupported construct in that file.
The four additional dataset record sources (`dataset-split`,
`dataset-item-summary`, `dataset-artifact`, `dataset-sync-entry`) were also
inspected: only `dataset-artifact@1` renders with the current flat reader;
the others require the constructs listed below.

| Selected schema(s) | Additional constructs required beyond the current flat reader |
|---|---|
| `verbalized@1`, `region-transcription@1` | None; existing strings, nullable/optional fields and string constraints suffice |
| `mathml@1`, `page-judgement@1` | `enum`; `maximum` for probabilities |
| `latex@1` | `maximum`, arrays with typed items and fixed length (`minItems`/`maxItems`) |
| `image@2` | `const`, `exclusiveMinimum`, nested objects and required properties |
| `media-inspection@1` | `enum`, nullable nested objects, arrays and open metadata objects, `exclusiveMinimum` |
| `pdf-validation-report@1` | `enum`, nested objects/arrays, required properties and typed string maps (`additionalProperties`) |
| `text-spans@1`, `dataset-item@1` | The above object/array rules plus local `definitions`/`$ref`; fixed-size coordinate arrays for spans; open metadata for items |
| `dataset-info@1` | String `enum` and arrays of strings |
| `layout-analysis@1` | Explicit local `$defs` selection; operational nested records, nullable fields, enums and bounds. SDK adapter for the known union branches; reuse docstruct for canonical fields, without compiling general `anyOf`/`allOf` |
| `dataset-split@1`, `dataset-item-summary@1`, `dataset-artifact@1` | Typed arrays, open metadata objects, integer bounds and nullable scalar fields; the artifact record already fits the flat reader |
| Five precise dataset array schemas | Root arrays, typed element references, local `definitions`/`$ref` and annotation metadata such as `$comment`; preserve empty arrays and share source record bindings |
| `dataset-sync-entry@1` / `dataset-sync-report@1` | A bounded status-based reader for the published `anyOf` branches (`status` `const` plus branch-specific `required` fields), including global skipped events with only status/reason; reject unsupported conditional patterns |

Continue failing explicitly on unknown constraints, non-local/unresolved or
recursive references and schema families outside this set. Do not add general
`anyOf`/`oneOf`/`allOf`, network reference resolution or canonical-manifest generation
to make this inventory green. Reuse docstruct's canonical types at adapter
boundaries, including document/geometry types where their semantics match;
do not generate competing canonical element, bounding-box or table models.
Generated operational models must use standard-library dependencies only.

## Compatibility and verification before migration

Each implementation PR must demonstrate how a generated model reaches its
intended reader, with representative responses and failures. Generating an
unused dataclass does not complete a binding. Preserve existing public return
shapes and SDK error classes, using additive typed readers/accessors when a
replacement would break compatibility. A deliberate stricter contract or
changed return type requires its own documented compatibility decision.

In particular:

- The math client and its [tests](../libs/sdk/tests/clients/test_math.py) accept
  both single-expression documents and legacy `formulas` lists. The latter is
  not the published flat `latex@1` schema. Preserve the normalization adapter;
  provider output conformance remains [Toolbox #117][provider-followup].
- [Formula operations](../libs/sdk/src/acessilia_sdk/operations/formula.py)
  distinguish an absent text key from a non-string value and support both
  conversion directions. A generated reader must not silently turn those
  cases into a different retry/degradation policy.
- `page_judgement_probability` currently accepts coercible probabilities,
  including numeric strings, and returns `None` for unusable answers. Its
  [tests](../libs/sdk/tests/clients/test_adjudicate_probability.py) are a
  compatibility baseline, distinct from strict schema validation.
- Binary artifact digests, PNG/PDF/DOCX magic, size bounds, endpoint affinity
  and applied clips remain the existing artifact/client checks; a generated
  metadata model cannot replace them.
- Preserve missing-vs-null measurements, unknown extension fields and open
  metadata. `ArtifactReference.from_dict` currently ignores unknown fields,
  even though its schema has `additionalProperties:false`; schema-driven
  generation must not silently change that forward-compatibility policy.

- Dataset sync now has a published array contract; object-shaped SDK mocks
  are a legacy characterization, not the generation source. Add schema-based
  array examples and typed readers without silently changing existing raw
  pass-through compatibility. Cover disabled mirroring, skipped item/artifact
  events and empty arrays. Preserve emitted nulls in dataset info/artifact
  records, and distinguish provider-raised listing errors from the existing
  missing-manifest/directory behavior that returns `[]`.

Generated `from_dict` checks must be compared with the published JSON Schema
on valid and invalid examples. Cover bounds, integer-vs-boolean values,
nullable/missing fields, nested arrays/objects and bad references. Keep
[SDK purity](../libs/sdk/tests/test_purity.py), generated-file drift checks in
[`test_sdk_bindings.py`](../tests/test_sdk_bindings.py) and the deployment-branch
[`check_capability_contract.py`](../scripts/check_capability_contract.py)
cross-check. Transport, retries, provider choices and agent policies are not
part of this sequence.

## Snapshot refresh and review sequence

The reviewed source set must be reproducible. For each generation PR:

1. Review the selected references in the Toolbox's public contract and its
   `schema_refs`/`dataset_routes`, and record the exact source commit. Before
   refreshing, extend capture to preserve these fields and immutable provenance;
   the current normalized fixture drops them.
2. Add only the reviewed schema filenames and model targets to
   `SDK_MODEL_SCHEMAS` and `MODELS`. Capture the contract and those schemas
   **from the same immutable Toolbox SHA**, through the capture script.
3. Regenerate; never edit the generated block, model modules or captured
   schemas by hand. Commit the capture provenance and generated changes
   together, and inspect the allowlist/transport diff separately.
4. Run drift, schema/consumer regression and purity checks and `make test-all`.
   CI's live deployment-branch contract check remains independent of the
   pinned generation snapshot; it must continue to run.

From the repository root, after step 2's explicit selection changes:

```bash
python scripts/capture_toolbox_contract.py --ref <immutable-toolbox-sha>
python scripts/generate_sdk_bindings.py
python scripts/generate_sdk_bindings.py --check
python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json
make test-all
```

This documentation PR is **PR 1: inventory and scope**. Review it before
**PR 2: nine selected operational models and the variant-aware layout binding**,
followed by **PR 3: six dataset record bindings and five precise REST array
bindings**. The dataset/layout publication prerequisites are resolved at the
pinned SHA. #213 closes only after the agreed selected set is used and drift-tested;
the seven deferred published execute families, unrelated capabilities,
catalogue/control/gateway responses and SDK-derived operation dataclasses do
not automatically join this generation scope.

[review]: https://github.com/A11yDevs/acessilia/issues/213#issuecomment-6904046274
[contract]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/contract/toolbox-contract.json
[schemas]: https://github.com/A11yDevs/acessilia-toolbox/tree/c536c2007912e0ce2f20bd930215d96e6f4c09be/schemas
[openapi]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/docs/openapi.json
[dataset-examples]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/tests/unit/test_dataset_contracts.py
[dataset-followup]: https://github.com/A11yDevs/acessilia-toolbox/issues/158
[layout-followup]: https://github.com/A11yDevs/acessilia-toolbox/issues/159
[provider-followup]: https://github.com/A11yDevs/acessilia-toolbox/issues/117

[dataset-publication]: https://github.com/A11yDevs/acessilia-toolbox/pull/160
[layout-publication]: https://github.com/A11yDevs/acessilia-toolbox/pull/161
[dataset-contract]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/docs/dataset-contracts.md
[layout-contract]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/docs/layout-contract.md

## Implementation review sequence

The implementation is split further to keep reviews bounded: pinned snapshot,
selected execute readers, variant-aware layout reader, then dataset REST readers.
Each subsequent PR targets the preceding branch until it is merged. The source
is pinned in `tests/fixtures/toolbox-snapshot.json`; it records byte-level SHA-256
checksums for the complete public contract and every selected schema. Live
`--url` captures are diagnostic files and cannot overwrite the generation input.
