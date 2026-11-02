<!--
Write the pull request in English (the constitution's English-first rule, section 2).
Delete the sections that do not apply; keep the checklist.
-->

## Why

<!-- The problem this solves, and the issue it belongs to. -->

Part of #

> `Closes #N` only closes the issue when the pull request merges into `main`, the default branch. For a pull request into `develop`, close the issue by hand after the merge.

## What changes

<!-- What changed, and anything a reviewer could not guess from the diff. -->

## Verification

<!-- How you checked it: tests, commands, a real run against a Toolbox. -->

## Architecture conformance

Principles P1–P9 are in [docs/constitution.md, section 7](https://github.com/A11yDevs/acessilia/blob/develop/docs/constitution.md); decisions are in [docs/adr](https://github.com/A11yDevs/acessilia/blob/develop/docs/adr/README.md). Check each item, or explain under it why it does not apply.

- [ ] **Owner (P1, P2).** The code lives in the component that owns it: core for decisions, planning and flows; SDK for contracts and access; docstruct for pure structural algorithms; Toolbox for operational execution. Nothing here duplicates an implementation that exists elsewhere (see the [audit](https://github.com/A11yDevs/acessilia/blob/develop/docs/architecture/audit-2026-10.md)).
- [ ] **Dependencies (P3).** The dependency direction holds (core → SDK, docstruct; SDK → docstruct; docstruct → nothing), with no import of another component's internals.
- [ ] **No local executor (P4, P6, [ADR-0003](https://github.com/A11yDevs/acessilia/blob/develop/docs/adr/0003-remote-only-operational-capabilities.md)).** No operational library, tool subprocess or local fallback was added to the core; a Toolbox failure is reported explicitly.
- [ ] **Contracts (P5, P7, P9).** Capabilities and artifacts are used through the SDK and their published contracts. Any contract change is versioned, and `tests/fixtures/toolbox-contract.json` is updated when the SDK's capability registry changes.
- [ ] **Small and separate (P8).** Architectural and behavioural changes are not mixed; a removal is preceded by its replacement.
- [ ] **Decision recorded.** A change of responsibilities, dependencies, execution mode or public contract, or an exception to a principle, has an ADR in this pull request or a link to an accepted one.

## Quality

- [ ] `uv run pytest -m "not e2e"` (the command CI runs) passes with no unexpected skip, and new behaviour has tests.
- [ ] User-facing strings go through `backend.i18n` with their pt-BR translation in `scripts/gen_locale_catalogs.py`, and the catalogs are regenerated.
- [ ] Every changed `.md` file has its `.pt-br.md` mirror updated in this pull request.
