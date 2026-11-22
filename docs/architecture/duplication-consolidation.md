# Duplication classification and first consolidation, November 2026

> A Brazilian Portuguese translation is available in
> [duplication-consolidation.pt-br.md](duplication-consolidation.pt-br.md).

This is PR 2 of [issue #656](https://github.com/A11yDevs/acessilia/issues/656). It triages the duplicate groups from the [November baseline](quality-baseline.md) and implements the first low-risk consolidation. The snapshot that seeded the triage is `develop` at `b00636fc`: **23 groups, 57 functions and 699 lines**.

## Method

- A structural group is actionable only when the functions are semantically interchangeable for the same callers. Equal normalized control flow is not enough.
- Generated code is changed through its generator, never by editing the generated file.
- Behaviour-sensitive flows (agent selection, frontend startup) need a characterization test before extraction.
- A cross-component duplicate needs a single owner. Locale parsing is i18n semantics and the generic parser now lives in the SDK (`acessilia_sdk.i18n`); the core keeps catalogs, policies and request context, and the service reads the environment and delegates the parse.

## First consolidation: the locale-list parser

Before this PR, two 15-line functions implemented the same rule — split on commas, trim each entry, drop blanks and duplicates, preserve first-seen order:

- `backend/config/settings.py::_locales_from_env`;
- `libs/core/src/acessilia_core/i18n/__init__.py::_locales_from_raw`.

After:

- `acessilia_sdk.i18n` exposes `parse_locales` and `normalize_locale` as generic infrastructure;
- `acessilia_core.i18n.parse_locales` remains as a temporary compatibility facade importing the SDK implementation;
- `Settings.i18n_locales_active` calls the SDK directly with `I18N_LOCALES_ACTIVE`;
- the backend's private copy is removed;
- `configure_locales` still filters the parsed list against `SUPPORTED_LOCALES`, so an empty or unsupported list keeps the existing “offer every supported locale” fallback.

The behaviour is pinned by `tests/test_i18n_locales.py` (including the core facade) and the SDK's `tests/test_i18n.py`: blank entries, duplicates, ordering, normalization and the `Settings` environment path. The SDK owns generic locale parsing/normalization; the core keeps its catalogs, policies and request context. The remaining i18n infrastructure migration is tracked in [#712](https://github.com/A11yDevs/acessilia/issues/712). This avoids making the core the mandatory owner of a cross-cutting utility and lets the service consume it without importing the core.

The core facade is a new compatibility name, not a preserved pre-existing caller: `_locales_from_raw` was dead code before this PR. It exists so the remaining migration can proceed without a flag day; #712 tracks its removal. The SDK release that publishes this API must also relax the core pin `acessilia-sdk>=0.3,<0.4` (new public API normally means 0.4.0).

**Measured delta on this PR's code commit:** 23 groups / 57 functions / 699 lines → **22 groups / 55 functions / 669 lines**. Only the `_locales_*` group disappears. The initial [baseline JSON](quality-baseline.json) stays as the historical snapshot; this page records the first change against it.

## Classification of the remaining groups

Baseline order from `docs/architecture/quality-baseline.json`; “candidate” means the next consolidation can evaluate it with tests, not that it is safe to merge immediately.

| # | Group | Disposition |
|---:|---|---|
| 0 | Frontend Telegram `cmd_detailed`, `cmd_low`, `cmd_medium`, `cmd_normal`, `cmd_ocr` (5/39) | Defer to a frontend PR: confirm user-facing copy and menu differences before extracting a command helper. |
| 1 | Generated SDK dataset readers (5/15) | Generated file (`_dataset_generated.py`): fix the generator, not the generated functions. |
| 2 | Core schema writers `write_*_schema` (4/33) | Candidate: a shared JSON-writer helper with schema-path tests. |
| 3 | Core config helpers `_tool_config`, `_export_config`, `_toolbox_config` (3/17) | Defer: the surrounding config dataclasses differ. |
| 4 | SDK result readers in adjudicate/pdf/pdf_validate (3/48) | Candidate: a generic typed-result reader after the SDK contract tests. |
| 5 | SDK result readers in math/media_inspect (3/38) | Candidate: same generic reader. |
| 6 | `_locales_from_env` / `_locales_from_raw` (2/30) | **Consolidated in this PR.** |
| 7 | `JobOperations.__init__` / `_FurnitureView.__init__` (2/6) | Trivial; no action. |
| 8 | Frontend `_is_process_running` (2/26) | Frontend follow-up with the lock/startup group. |
| 9 | Frontend `acquire_lock` (2/36) | Frontend follow-up with the lock/startup group. |
| 10 | Frontend `startup` (2/107) | High-value frontend follow-up; needs startup characterization. |
| 11 | `ApiClient._admin_headers` / `_operations_headers` (2/10) | Candidate small helper; low priority. |
| 12 | Telegram `cmd_ativar` / `cmd_desativar` (2/20) | Defer: user-facing command copy. |
| 13 | Agent `select_page` in adjudication/page-level (2/56) | Behaviour-sensitive: characterize selection policy first. |
| 14 | Agent `swap_low_agreement` (2/52) | Behaviour-sensitive: characterize the swap policy first. |
| 15 | `process_join_tail` in fusion/page-level (2/30) | Evaluate with the agent follow-up. |
| 16 | Output schema normalizers (2/10) | Candidate small helper. |
| 17 | Table specialist `select_greedy` / `select_table` (2/40) | Behaviour-sensitive: table selection tests first. |
| 18 | Core `_sha256` in builder/domain bundle (2/12) | Candidate utility consolidation. |
| 19 | Math async wrappers (2/12) | Candidate small wrapper helper. |
| 20 | Pandoc `_contains_math` / `_count_math_nodes` (2/18) | Candidate small helper. |
| 21 | SDK layout/structure result readers (2/32) | Candidate: same generic result reader as groups 4–5. |
| 22 | `_check_artifact_id` / `_check_digest` (2/12) | Candidate small validation helper. |

The next highest-value candidates are the frontend startup/lock trio (groups 8–10), the SDK result readers (4, 5, 21) and the core schema writers (2). Each should get its own focused PR with the relevant characterization tests; none was changed here.

## Reproduction

```bash
python scripts/architecture_quality.py --rev b00636fc   # initial baseline
python scripts/architecture_quality.py --rev HEAD       # current numbers
python -m pytest tests/test_i18n_locales.py
```

The machine-readable initial snapshot remains in [quality-baseline.json](quality-baseline.json). The classification is intentionally about candidates; PR 5 will decide which remaining measures become a CI guard.
