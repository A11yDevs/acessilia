# More resilient document extraction and artifact retrieval

## Problems and symptoms

- Oversized PDFs could reach costly structural extraction before the page limit was checked.
- A temporary artifact-upload failure could stop otherwise available direct extraction.
- An artifact download could stop at a 404 even when another endpoint stored the file.
- Dual extraction could terminate on a failed primary without trying the secondary.
- Independent upload/extraction clients could send an artifact ID to the wrong deployment.

## Implemented solutions

Verified PDF page counts from `media.inspect` are checked before structural
extraction. Only the parser-backed `pymupdf` count is trusted for early rejection;
unknown/estimated counts retain the authoritative post-extraction limit.

Transient upload failures use direct source input, with a translated warning
and a recorded failure category. Authentication, invalid-input and contract
errors are not bypassed. Independent deployments also use direct source input
by policy, while a single deployment retains reference-based input.

Artifact downloads alone search the next compatible endpoint after a 404.
Other operations and error codes retain their behavior. All-404 results remain
not-found errors; content verification and atomic replacement remain mandatory.

Dual providers are attempted independently. Both successful results retain the
existing fusion; a single successful provider supplies the result with explicit
degradation and matching provenance/cache information. If neither succeeds,
the failure preserves both causes. Unexpected programming errors are not hidden.

## Storage-outage compatibility

Direct input avoids the initial artifact upload, but extraction can still fail
if the Toolbox requires storage for its output JSON. Continuing through this
outage requires the complementary change in
[Toolbox PR #100](https://github.com/A11yDevs/acessilia-toolbox/pull/100):
on a temporary storage failure, an inline-only extraction returns its JSON
without claiming a stored download or caching the unpersisted result.
Required binary outputs and by-reference capabilities still require storage;
permanent input or contract errors are not bypassed.

A cross-project regression in the Toolbox exercises the real Core extractor
and SDK against a real local Toolbox HTTP server in separate Python
environments. Both the initial upload and JSON persistence fail, while a stub
extractor succeeds. The Core receives the inline document and records the
upload failure. This verifies transport and orchestration, not extraction
quality or a complete production conversion pipeline.

## Validation and review

[GitHub Actions run 40728598705](https://github.com/A11yDevs/acessilia/actions/runs/40728598705)
validated the release PR merge candidate for head
`ee81a23eadce9397aa57c92b6af0965194526be5`: 1,899 Core tests,
833 Docstruct tests and 250 SDK tests passed. The normal workflow excluded 51
E2E tests and reported no unexpected skipped tests. These counts describe that
specific run, not a guarantee about later commits.

The corrections are under review in
[Core PR #309](https://github.com/A11yDevs/acessilia/pull/309). The earlier
golden-manifest mismatch was addressed by request-time translation and an
explicit canonical test locale; see [manifest localization](manifest-localization.md).

No dataset benchmark or production rollout was performed. Independent storage
systems do not become shared, and availability is not guaranteed when all
providers fail. Storage-outage continuity requires deploying the complementary
Toolbox change alongside the Core fallback.
