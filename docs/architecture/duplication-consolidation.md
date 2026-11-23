# Duplication classification and consolidations, November 2026

> A Brazilian Portuguese translation is available in
> [duplication-consolidation.pt-br.md](duplication-consolidation.pt-br.md).

This is PR 2 of [issue #656](https://github.com/A11yDevs/acessilia/issues/656). It triages the duplicate groups from the [November baseline](quality-baseline.md) and records the low-risk consolidations implemented so far. The snapshot that seeded the triage is `develop` at `b00636fc`: **23 groups, 57 functions and 699 lines**.

## Method

- A structural group is actionable only when the functions are semantically interchangeable for the same callers. Equal normalized control flow is not enough.
- Generated code is changed through its generator, never by editing the generated file.
- The duplicate detector ignores bodies with fewer than two statements. A one-statement wrapper is not evidence of consolidation; the exemption is recorded here so it does not silently lower the metric.
- Behaviour-sensitive flows (agent selection, frontend startup) need a characterization test before extraction.
- A cross-component duplicate needs a single owner. Locale parsing is i18n semantics and the generic parser now lives in the SDK (`acessilia_sdk.i18n`); the core keeps catalogs and policies, the SDK owns request context and translation, and the service reads the environment and delegates the parse.

## First consolidation: the locale-list parser

Before this PR, two 15-line functions implemented the same rule — split on commas, trim each entry, drop blanks and duplicates, preserve first-seen order:

- `backend/config/settings.py::_locales_from_env`;
- `libs/core/src/acessilia_core/i18n/__init__.py::_locales_from_raw`.

After:

- `acessilia_sdk.i18n` exposes `parse_locales` and `normalize_locale` as generic infrastructure;
- `acessilia_core.i18n.parse_locales` existed during the migration as a temporary compatibility facade importing the SDK implementation; the final #712 PR removed it;
- `Settings.i18n_locales_active` calls the SDK directly with `I18N_LOCALES_ACTIVE`;
- the backend's private copy is removed;
- `configure_locales` still filters the parsed list against `SUPPORTED_LOCALES`, so an empty or unsupported list keeps the existing “offer every supported locale” fallback.

The behaviour is pinned by `tests/test_i18n_locales.py` and the SDK's `tests/test_i18n.py`: blank entries, duplicates, ordering, normalization, the `Settings` environment path and the absence of a core re-export. The SDK owns generic locale parsing/normalization; the core keeps its catalogs and policies. The rest of the i18n infrastructure migration was completed in [#712](https://github.com/A11yDevs/acessilia/issues/712). This avoids making the core the mandatory owner of a cross-cutting utility and lets the service consume it without importing the core.

The core facade was a new compatibility name, not a preserved pre-existing caller: `_locales_from_raw` was dead code before this PR. It existed so the remaining migration could proceed without a flag day; #712 removed it and moved the core pin to `acessilia-sdk>=0.4,<0.5` when SDK 0.4.0 published the full i18n API.

**Measured delta on this PR's code commit:** 23 groups / 57 functions / 699 lines → **22 groups / 55 functions / 669 lines**. Only the `_locales_*` group disappears. The initial [baseline JSON](quality-baseline.json) stays as the historical snapshot; this page records the changes against it.

## Second consolidation: the JSON Schema writer

The four `write_*_schema` functions in `execution/schema.py`, `manifest/schema.py`
and `planning/schema.py` repeated the same parent creation, UTF-8 encoding,
`json.dumps(ensure_ascii=False, indent=2)` and trailing newline. They now delegate
to `acessilia_core.schema_files.write_schema`, while each module keeps its own
schema function and public writer name. The tests compare each writer's output
with its schema function and cover parent creation and non-ASCII JSON.

The formatting of the committed schema files is unchanged; the schema writer PR
did not regenerate their contents. A follow-up (#737) made the descriptions
canonical English, regenerated the three drifted files and added a freshness
test. This removes the `write_*_schema` group from the remaining candidates.

**Measured delta on this PR's code commit:** 24 groups / 59 functions / 705
lines → **23 groups / 55 functions / 672 lines**. Only the `write_*_schema`
group disappears.

## Third consolidation: the frontend entry point

`frontend/cli/run.py` was a near-copy of `frontend/run.py`: the same PID probe,
process lock and interface startup, differing only in formatting, the lock file
location and the presence of a `main()` function. The console-script entry point
now imports `main` from `frontend.run`, so the runtime has one implementation and
one lock (`frontend/bot.lock`). Starting either entry point while the other is
already running is now refused, instead of using two separate lock files. The
runtime also recognizes the legacy `frontend/cli/bot.lock`: if it names a live
process, startup is refused; if it is stale or malformed, it is removed.

The startup and lock behaviour is pinned by `tests/test_frontend_startup.py`:
every enabled interface, the missing-token and empty-interface exits, the lock
lifecycle (live, stale and malformed files), and the POSIX/Windows PID probes.
`tests/test_process_setup.py` keeps checking that the runtime sets up the process
before it takes the lock.

**Measured delta on this PR's code commit:** 23 groups / 55 functions / 672
lines → **20 groups / 49 functions / 499 lines**. The `_is_process_running`,
`acquire_lock` and `startup` groups disappear.

## Fourth triage: the SDK typed-result wrappers

The three SDK groups are false positives for consolidation. Validation already
lived in the shared readers: `read_result`/`read_document` for execute results,
`read_layout`/`read_manifest` for the layout and structure documents. The
duplicate was only the two-statement forwarding shape (`await` the raw client
method into a temporary, then pass it to the reader). The accessors now inline
the awaited call into their reader, so the public signatures and the reader
behaviour stay the same while the forwarding is explicit and the temporary
disappears. `judge_page_result`, which was outside the groups, follows the same
shape for consistency.

This covers `judge_page_result`, `transcribe_region_result`, `text_spans_result`,
`validate_result`, `convert_result`, `verbalize_result`, `inspect_result`,
`analyze_result` and `extract_structure_result`. The existing result-reader and
layout-reader tests exercise both valid and invalid outputs.

The detector now reports 20 groups / 49 functions / 499 lines → **17 groups / 41
functions / 381 lines**, but this is a detector exemption, not an extraction of
shared behaviour: every rewritten body has one statement, and `_fingerprint`
ignores bodies with fewer than two statements. The eight wrappers in those
groups would be grouped again if that floor changed. The three rows stay recorded
as reclassified rather than consolidated until the detector's one-statement
policy is decided for the CI guard of PR 5; [#749](https://github.com/A11yDevs/acessilia/issues/749)
tracks that decision.

## Fifth consolidation: the Telegram command helpers

The five mode commands (`/ocr`, `/detalhado`, `/medio`, `/baixo` and `/normal`)
repeated the same two steps: store the next-file mode for the sender's chat and
topic, then send the localized confirmation. They now share `_set_mode`. The
pause/resume pair shares `_set_pause`, which receives the action (`pause_chat`
or `resume_chat`) and the reply id. Command names, aliases and user-facing copy
are unchanged; the parameterized tests cover every mode and both pause actions.

**Measured delta on this PR's code commit:** 17 groups / 41 functions / 381
lines → **15 groups / 34 functions / 324 lines**. The five-mode group and the
pause/resume **command** group disappear; the `pause_chat`/`resume_chat`
middleware functions remain a separate group.

## Sixth consolidation: the Telegram pause middleware

`pause_chat` and `resume_chat` repeated the same three steps: update the
in-memory paused-chat cache, persist the change through `TelegramStateStore`,
and log a warning when SQLite is unavailable. They now share `_set_paused`,
which keeps the cache update before the store call and preserves the failure
path. The state-survival and store-failure tests cover both actions.

**Measured delta on this PR's code commit:** 16 groups / 36 functions / 333
lines → **15 groups / 34 functions / 319 lines**. The pause/resume middleware
group disappears.

## Seventh consolidation: the blank optional-string normalizer

`VisionOutput.normalize_empty_formula_latex` and
`DataOutput.normalize_empty_optional_strings` implemented the same rule: a
provider's blank optional string means the field is absent. Both validators now
delegate to `_blank_to_none`; the existing tests cover `formula_latex`, `latex`
and `caption`.

**Measured delta on this PR's code commit:** 15 groups / 34 functions / 319
lines → **14 groups / 32 functions / 309 lines**. The output-schema normalizer
group disappears. Both delegating validators now have one statement, so the
detector's `< 2 statements` exemption hides them; they would be grouped again
if [#749](https://github.com/A11yDevs/acessilia/issues/749) changes that floor.
Unlike the SDK wrapper case, this is a real extraction: both validators share
`_blank_to_none`.

## Eighth consolidation: the file SHA-256 helper

The manifest builder and the planning domain bundle repeated the same chunked
SHA-256 implementation. Both now call `acessilia_core.hashing.file_sha256`,
which uses `hashlib.file_digest`; the toolbox extractor's equivalent
`_source_sha256` was removed as well. Tests cover empty, small, multi-chunk and
missing files, and both `Path` and `str` paths.

**Measured delta on this PR's code commit:** 14 groups / 32 functions / 309
lines → **13 groups / 30 functions / 297 lines**. The `_sha256` group disappears;
the toolbox extractor copy did not form a group, so it does not change this
delta.

## Ninth consolidation: the API auth-header helper

`ApiClient._admin_headers` and `_operations_headers` repeated the same base-header
copy and bearer-token rule. Both now delegate to `_auth_headers`; a test pins the
observability token together with the API key, and the existing operations-token
tests cover the other branch. Another test configures both tokens and checks
that admin routes receive only the observability token while `/cache/clear`
receives only the operations token.

**Measured delta on this PR's code commit:** 13 groups / 30 functions / 297
lines → **12 groups / 28 functions / 287 lines**. The auth-header group
disappears.

## Tenth consolidation: the Pandoc math-node walk

`_count_math_nodes` and `_contains_math` repeated the same list/dict traversal
over Pandoc nodes. Both now use `_math_nodes`, a pre-order generator; counting
consumes it, and containment stops at the first match. Direct walk, count and
degradation tests cover the shared traversal.

**Measured delta on this PR's code commit:** 12 groups / 28 functions / 287
lines → **11 groups / 26 functions / 269 lines**. The Pandoc math-node group
disappears.

## Eleventh consolidation: the math client lifecycle

Recognition, conversion and verbalization each created a `ToolboxMathClient`,
awaited one SDK operation and closed the client. All three now use
`_with_math_client`; the operation callback keeps the same SDK call and the
client is closed in `finally`.

**Measured delta on this PR's code commit:** 11 groups / 26 functions / 269
lines → **10 groups / 24 functions / 257 lines**. The math async-wrapper group
disappears.

## Twelfth consolidation: the generated dataset readers

The five dataset collection readers in `_dataset_generated.py` repeated the
local `decode` import and call. The generator now emits a shared `_read` helper;
each public reader keeps its precise rule and name and becomes one line. The
generated-file freshness test pins the output, and the dataset reader/schema
tests cover valid, empty and malformed documents.

**Measured delta on this PR's code commit:** 10 groups / 24 functions / 257
lines → **9 groups / 19 functions / 242 lines**. The generated dataset-reader
group disappears. Each reader is now one statement, so the detector's
one-statement floor also applies; the shared helper is the actual extraction,
not the floor.

## Classification of the remaining groups

Baseline order from `docs/architecture/quality-baseline.json`; “candidate” means the next consolidation can evaluate it with tests, not that it is safe to merge immediately.

| # | Group | Disposition |
|---:|---|---|
| 0 | Frontend Telegram `cmd_detailed`, `cmd_low`, `cmd_medium`, `cmd_normal`, `cmd_ocr` (5/39) | **Consolidated:** shared `_set_mode`; copy and aliases unchanged. |
| 1 | Generated SDK dataset readers (5/15) | **Consolidated:** the generator emits shared `_read`; readers keep their rules. |
| 2 | Core schema writers `write_*_schema` (4/33) | **Consolidated:** shared `schema_files.write_schema`, with writer/schema tests. |
| 3 | Core config helpers `_tool_config`, `_export_config`, `_toolbox_config` (3/17) | Defer: the surrounding config dataclasses differ. |
| 4 | SDK result readers in adjudicate/pdf/pdf_validate (3/48) | **Reclassified:** false positive; the shared reader already owns validation. |
| 5 | SDK result readers in math/media_inspect (3/38) | **Reclassified:** false positive; inlining is style-only, not extraction. |
| 6 | `_locales_from_env` / `_locales_from_raw` (2/30) | **Consolidated in this PR.** |
| 7 | `JobOperations.__init__` / `_FurnitureView.__init__` (2/6) | Trivial; no action. |
| 8 | Frontend `_is_process_running` (2/26) | **Consolidated:** one runtime behind both entry points, with PID-probe tests. |
| 9 | Frontend `acquire_lock` (2/36) | **Consolidated:** the console script shares `frontend.run` and its lock. |
| 10 | Frontend `startup` (2/107) | **Consolidated:** characterization covers interface composition and shutdown. |
| 11 | `ApiClient._admin_headers` / `_operations_headers` (2/10) | **Consolidated:** shared `_auth_headers`. |
| 12 | Telegram `cmd_ativar` / `cmd_desativar` (2/20) | **Consolidated:** shared `_set_pause`; copy unchanged. |
| 13 | Agent `select_page` in adjudication/page-level (2/56) | Behaviour-sensitive: characterize selection policy first. |
| 14 | Agent `swap_low_agreement` (2/52) | Behaviour-sensitive: characterize the swap policy first. |
| 15 | `process_join_tail` in fusion/page-level (2/30) | Evaluate with the agent follow-up. |
| 16 | Output schema normalizers (2/10) | **Consolidated:** shared `_blank_to_none`. |
| 17 | Table specialist `select_greedy` / `select_table` (2/40) | Behaviour-sensitive: table selection tests first. |
| 18 | Core `_sha256` in builder/domain bundle (2/12) | **Consolidated:** shared `hashing.file_sha256`. |
| 19 | Math async wrappers (2/12) | **Consolidated:** shared `_with_math_client` lifecycle. |
| 20 | Pandoc `_contains_math` / `_count_math_nodes` (2/18) | **Consolidated:** shared `_math_nodes` walk. |
| 21 | SDK layout/structure result readers (2/32) | **Reclassified:** false positive; the envelope extraction is already shared. |
| 22 | `_check_artifact_id` / `_check_digest` (2/12) | Candidate small validation helper. |

The table is anchored to the November baseline. The current tool also reports
two groups outside it: the two deprecation `__getattr__` functions in
`table_ast`/`validators` (2/20) and the planner property shared by the
orchestrator and the planning engine introduced by #632 (2/9); they are tracked
separately from the baseline rows.

The remaining groups are smaller or behaviour-sensitive. Agent selection and
table selection need characterization before extraction, while the config
helpers stay deferred for the reasons in the table. Each consolidation should
keep its own focused PR; the remaining groups were not changed here.

## Reproduction

```bash
python scripts/architecture_quality.py --rev b00636fc   # initial baseline
python scripts/architecture_quality.py --rev HEAD       # current numbers
python -m pytest tests/test_i18n_locales.py libs/core/tests/test_schema_files.py libs/core/tests/test_hashing.py libs/docstruct/tests/test_pandoc_ast_degrade.py tests/test_api_client.py tests/test_frontend_startup.py tests/test_telegram_client.py tests/test_telegram_state.py tests/test_structured_agent_outputs.py tests/test_toolbox_math_tools.py tests/test_sdk_bindings.py tests/test_sdk_dataset_schema.py libs/sdk/tests/test_dataset_readers.py libs/sdk/tests/test_result_readers.py libs/sdk/tests/test_layout_readers.py
```

The machine-readable initial snapshot remains in [quality-baseline.json](quality-baseline.json). The classification is intentionally about candidates; PR 5 will decide which remaining measures become a CI guard.
