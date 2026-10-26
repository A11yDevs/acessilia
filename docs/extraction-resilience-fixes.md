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

## Validation and conclusion

Functional regressions were exercised before and after changes. The focused
core suite passed 81 tests and the SDK passed 250 tests. These checks are not
an evaluation of extraction quality. No dataset benchmark or production rollout
was performed. The previously observed golden-manifest mismatch has been
addressed by request-time translation and an explicit canonical test locale;
see [manifest localization](manifest-localization.md).


The changes avoid unnecessary extraction, preserve useful results during
recoverable failures and prevent cross-deployment artifact assumptions in the
initial input. They do not make independent storage systems share objects or
guarantee availability when every provider is down. Further work is committed on the fork work branch without opening or updating
pull requests. The complete test status is recorded below.

Latest complete core validation after the localization correction: **1,775 passed,
51 E2E tests deselected**, with no failures. The separate SDK validation remains
250 passing tests; no SDK behavior changed in the localization correction.
