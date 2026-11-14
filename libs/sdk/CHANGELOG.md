# Changelog

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](CHANGELOG.pt-br.md)

The SDK is a public API for scripts and benchmarks (#402). Changes that a caller
can see are recorded here, newest first.

## Unreleased

- **Added** operation identifiers and cancellation (ADR-0019): `operation_context`
  and `operation_attempt` attach `task_id`, a stable `operation_id` and a fresh
  `attempt_id` to Toolbox capability and artifact headers, without reading
  settings. `ToolboxOperationClient.cancel` asks the configured endpoints to
  stop an operation with a short timeout and returns `OperationCancelResult`
  (`cancel_requested`, `cancelled`, `finished`, `failed` or `not_found`) instead
  of raising; a failed cancel is for the caller to record (#409).
- **Added** `convert_formula` and `verbalize_formula` in
  `acessilia_sdk.operations.formula`, one step per capability (`math.convert`,
  in either direction, and `math.verbalize`), each returning a `FormulaText`
  (the text, `""` when the answer has none, and its `Step`). `speak_formula`
  now runs the two; its result is unchanged for answers inside the contract. A caller that handles the two
  capabilities apart, like the core, calls the steps (#470, phase 3).
- **Changed** an answer of `math.convert` or `math.verbalize` outside the
  contract (no document object, or a value that is not a string, `null`
  included) raises `ToolboxContractViolation` in these steps and in
  `speak_formula`, instead of passing for a formula without that text. An
  answer whose document lacks the key is still `""`. `convert_formula` refuses
  a `direction` other than `latex-to-mathml` and `mathml-to-latex` with
  `ValueError`.

- **Added** `acessilia_sdk.operations.formula`, the SDK's first operation
  (ADR-0017, #470 phase 3): `crop_formula_region` renders a formula's box at
  200 dpi with `pdf.render` (a box that cannot be used, or a crop thinner than
  4 units, is no crop, never the whole page); `recognize_formula` sends the
  crop to `math.recognize` and ranks the LaTeX candidates; `speak_formula`
  converts LaTeX to MathML and verbalizes it; `formula_chain` runs the three
  for one formula. Each step reports its capability, provider and parameters,
  and raises the typed errors unchanged. The command line gains `formula`,
  which runs the chain and prints every step as JSON.
- **Changed** the SDK now depends on `acessilia-docstruct` (`>=0.5,<0.6`), for
  `best_effort_clip` and `ranked_latex_candidates`. docstruct is not on a
  package index: install `./libs/docstruct`, or its release wheel, before the
  SDK. Inside the repository, uv resolves it from its path.

- **Changed** `ToolboxEndpoint` now rejects, at construction, a base URL whose
  port is not a number or is outside 0–65535, and any URL `httpx` cannot parse,
  with `ValueError`. A misconfigured `TOOLBOX_BASE_URL` is then reported by the
  availability gate as an unavailable Toolbox instead of surfacing later as
  `httpx.InvalidURL`; the command line's own port check is gone because
  `parse_endpoints` now covers it (#438).
- **Documented** the public API: what each module lists in `__all__`
  (ADR-0018). A name outside it is internal and may change in any release. The
  README's table summarizes it, now including `ToolboxPdfValidateClient`, and
  `tests/test_public_api.py` checks it against `__all__`. No code changed.
- **Added** `page_judgement_probability(document)` in
  `acessilia_sdk.toolbox.clients.adjudicate`: the `pB` of a
  `document.adjudicate.page` answer as a float in [0, 1], or `None` when it is
  missing, not a number, NaN or out of range. The core's reading moved here
  (#402).
- **Added** `RENDER_MEDIA_TYPES` in `acessilia_sdk.toolbox.clients.pdf`: the inputs
  `pdf.render@2` opens (PDF, PNG, JPEG), for a caller to check before it sends
  a file. `render` itself does not check it, as before (#402).
- **Added** `ToolboxPdfClient.text_spans_by_page(file_path, artifact_id, *, pages,
  use_remote_cache)`: the `text-spans@1` page of each requested page, by page
  number. It asks each page once, in order, in calls of at most
  `TEXT_SPANS_MAX_PAGES` pages, and makes no call for no pages; every answer is
  checked as `text_spans` checks it. The core's batching moved here (#402).

## 0.3.0 (2026-11-11)

- **Added** `run`, `upload` to the command line. `run CAPABILITY` calls any
  `execute` capability of the registry through
  `POST /v1/capabilities/{id}:execute`, with the registry's provider and
  contract version unless `--provider` says otherwise, an input given as
  `--file` or `--artifact`, and optional `--language`, `--parameters` (a JSON
  object) and `--no-cache`; it prints the response envelope. `upload FILE`
  stores a file and prints its artifact id. `dataset list | describe | splits
  | items | item | artifact | sample | sync` reach the eight `dataset.*`
  routes through `ToolboxDatasetClient`, so every `rest` capability of the
  registry has a command; `run` refuses a `rest` capability before any
  request and names that command, and refuses a capability outside the
  registry. Every command reports each endpoint it fails over from on
  standard error (#402).
- **Changed** `--timeout` without a value: `catalog` keeps its 10 s; `run`,
  `upload` and `download` use the clients' default, since a capability can run
  for minutes. Before this release `download` also defaulted to 10 s.
- **Added** a command line, `python -m acessilia_sdk` (`acessilia_sdk.cli`):
  `catalog` prints the first endpoint's catalogue as JSON, and `download`
  fetches a stored artifact, checked against its digest and written
  atomically, trying the endpoints in order. Configuration comes only from
  arguments (`--endpoint`, `--api-key-file`, `--timeout`); exit status 1 for
  a Toolbox or file-system failure, 2 for invalid arguments (#402).
- **Added** `recognized_formulas(document)` (`acessilia_sdk.toolbox.clients.math`):
  the formulas of a `math.recognize@1` document as one list, whichever of its
  two shapes the provider answers with (`artifact/latex@1` from the chip
  models, a `formulas` list from `docling-math`). It moved unchanged from the
  core's `toolbox_math_tools`, which keeps what to do with the result (#402).
- **Added** `artifact_endpoint_urls(*clients)` and `one_artifact_endpoint(*clients)`
  (`acessilia_sdk.toolbox.artifacts`): the URLs a set of clients may address,
  and whether an artifact id can be shared among them (at most one URL;
  ADR-0006, ADR-0013). They were private helpers of the core's extractor,
  which keeps the decision to upload or send the file (#402).
- **Added** `ToolboxDatasetClient.list_all_items(dataset_id, split, *,
  revision, limit, page_size)`: every item of a split, or the first `limit`,
  read page by page on one client (`MAX_PAGE_SIZE = 1000`, the Toolbox's cap);
  a failed page raises its typed error rather than returning a partial list.
  The benchmark harness pages with it (#402).
- **Added** `read_catalog` takes an optional `api_key`, used when the endpoint
  has no key of its own, as the capability clients do. The core's
  availability gate passes its clients' key with their primary endpoint
  (#402).
- **Added** `read_catalog(endpoint, *, timeout_seconds)`
  (`acessilia_sdk.toolbox.catalog`): reads one endpoint's catalogue on a
  short-lived HTTP client, with the caller's per-request timeout and no
  retries. The core's availability gate uses it instead of building its own
  client (#402).
- **Added** `ArtifactReference` (`acessilia_sdk.toolbox.reference`), the
  published `artifact/reference@1`, generated from the Toolbox's schema;
  `parse_reference`, which also checks `digest == artifact_id`; and
  `ToolboxArtifactClient.upload_reference`. `upload()` and `ArtifactRef.parse`
  are unchanged (#185).
- **Changed** The registry's `output_schema` and `idempotent` are generated
  from the Toolbox's published contract by the core's
  `scripts/generate_sdk_bindings.py` (#213); the allowed ids, versions,
  transports, provider keys and labels stay hand-written in `_selected(...)`.
  `TOOLBOX_CAPABILITIES` is unchanged, field by field.
- **Changed** Retries and failover apply only to capabilities the registry
  marks `idempotent` (ADR-0006, #406). After a timeout or an unavailable
  instance, a call to `dataset.sample` gets one attempt on the first endpoint
  and raises that attempt's error; it was re-sent before, to the same and to
  another endpoint. Idempotent capabilities keep their retries, backoff and
  failover.
- **Changed** `ToolboxCapability` has a required keyword field `idempotent`,
  the manifest's `execution.idempotent` at `contract_version`. Every registry
  entry sets it; only `dataset.sample` is `False` (#406). A caller that builds
  its own `ToolboxCapability` must pass it.

## 0.2.0 (2026-11-09)

- **Added** `ToolboxClientConfig` and `make_client` (`acessilia_sdk.toolbox.config`,
  also exported from `acessilia_sdk.toolbox`). A caller builds every client
  setting as an explicit value and gets a configured client, with no core
  install. The core's `make_toolbox_client` now delegates to it; the clients it
  builds are unchanged (#402, step 1).
- **Added** a test that fails if any SDK module reads the process environment
  (`os.environ`, `os.getenv`, through any name `os` is imported as), as
  ADR-0002 requires.
- `acessilia_sdk.__version__` reports 0.2.0, and a test keeps it equal to the
  version in `pyproject.toml`.

## 0.1.0

The first version, before this changelog: the capability registry, the
transport, the per-capability clients, endpoints and failover, artifacts, the
catalogue, the VLM gateway helpers and `run_sync`.
