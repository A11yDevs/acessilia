# 0025. Share format identity and delivery metadata with a worker-owned plan

Brazilian Portuguese: [português brasileiro](0025-format-catalogue-ownership.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-17
- **Components:** docstruct, Core, service, web frontend
- **Issue:** [#371, E1.9](https://github.com/A11yDevs/acessilia/issues/371)

## Context

Export dispatch, the worker, token discovery and download surfaces repeated
format names, media types and suffixes. These consumers have different roles:
`pdf` remains downloadable for old jobs, only `pdf_ua` is produced now, ZIP is a
package, and benchmark Markdown is internal. The approved review explicitly
rejects equating their format sets. Issue #161 D3/D9 assigns format identity,
delivery policy and execution policy to different owners.

## Decision

- docstruct owns the frozen, standard-library-only
  `docstruct.export.formats.FormatSpec(id, version, media_type, extension, execution)`.
  It contains no registry, renderer, translation or I/O. `extension` is the file
  type (`pdf` for PDF/UA); delivery suffixes are separate. `version` identifies
  the binding revision, not a binary format specification.
- Core owns `acessilia_core.export.catalog`: frozen `FormatDelivery` records in
  a read-only catalogue. Delivery metadata describes status, production,
  download and package roles, canonical dispatch, legacy identity, suffix,
  display msgid and intrinsic detail levels. DOCX/PDF/UA reference the public
  SDK clients and capability registry for capability id, revision and MIME;
  they do not copy that registry. The existing SDK/Toolbox contract gate remains
  the authority for remote contract drift.
- The service owns `backend.api.export_plan.ExportStep`: order, required versus
  optional behavior, feature flags, stage msgids and progress. The worker uses
  this plan and the catalogue without changing serial order, cancellation
  checks, optional failure cleanup, concurrent audio/audit, or ZIP entry order.
  ZIP has no extra stage/progress update today; its plan fields are `None`.
  Package order is explicit because it differs from production order; the
  existing audit sidecar is appended last and is not a new public format.
- `execution` describes current routes: `local_pure` for pure serializers,
  `remote` for SDK renderers, `local` for consumer-owned audio/packaging, and
  `None` for legacy PDF without a producer. These last two extend the D3 draft
  enum to represent actual behavior. They authorize no new executor or local
  fallback: edge-tts retains its recorded ADR-0003 / Toolbox #73 deviation;
  ZIP is application packaging, never an operational provider in docstruct.
- Tokens, API downloads and the web panel derive their common metadata from
  the catalogue. Preserve the seven download identities, order, MIME types,
  `pdf_ua.pdf` / `_acessivel.zip` suffixes and historical API `label` tokens
  (`texto`, `word`, `pdf`, `pdf/ua`, `html`, `audio`, `completo`). These tokens are
  wire compatibility, not translation msgids. Existing web display msgids and
  translations move to Core; old `WEB_FORMAT_*` imports remain aliases. Email
  keeps its existing prose-specific labels and receives only completed public
  formats from the worker.
- Stable entries can be offered; experimental entries require explicit opt-in;
  internal entries are never offered. Current public surfaces offer stable
  downloadable entries only. No speculative format or user opt-in flag is added.
- Detail levels describe a format's representational capacity, not the current
  profile selection. Existing filters, audit gate, renderer signatures and
  AST/error order remain unchanged. E1.11/profile behavior and strict schema
  activation E1.2b require separate compatibility reviews.

## Consequences

A delivery metadata change has one source across the download surfaces; a new
producer still needs an explicit renderer binding and worker plan. No caller
is forced to equate production, canonical dispatch, package and download sets.
The additive identity is versioned in docstruct 0.5.4; Core's new public catalogue
is versioned 0.1.1, with its docstruct minimum raised to 0.5.4. No new dependency,
external pin, release publication, schema or export snapshot changes here.

Contract tests freeze names, wire labels, MIME, roles, SDK references, flags,
required failures, optional failures and archive order. Existing characterization,
standalone wheel, purity and pinned-container gates remain applicable. Replacing
legacy PDF, enabling experimental formats or changing failure policy needs its
own reviewed change.
