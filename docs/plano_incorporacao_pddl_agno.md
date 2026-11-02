# PDDL + Agno Incorporation Plan

You can also read this documentation in **Brazilian Portuguese**: [português brasilei](plano_incorporacao_pddl_agno.pt-br.md)

## Goal
Incorporate, incrementally and with validation, the architectural changes documented in:
- MVP_CHANGES.md
- PMV_2_CHANGES.md
- PMV_2_1_CHANGES.md

Remote reference: https://github.com/marceloakira/acessilia

## Current State
- [x] working branch created: feat/arquitetura-pddl-agno
- [x] remote added: marceloakira
- [x] changelogs imported and committed
- [x] Block 1 imported (static artifacts)
- [x] Block 2 imported (structural manifest)
- [x] Block 3 imported (PDDL planning)
- [x] Block 4 imported (execution/Agno)
- [ ] consolidation and hardening

## Execution Log
- Block 1:
	- files imported: `docs/pmv_agno_pddl.md`, `schemas/*.json`, `core/planning/domains/domain_v2.2.pddl`;
	- validation: JSON schemas are valid; focused tests without external dependencies pass (`16 passed`).
- Block 2:
	- files imported: `core/manifest/*`, `core/agno_support.py`, `core/agents/informational_structural.py`, the schema script and dedicated tests;
	- validation: Python syntactic compilation passes for all imported files;
	- environment limitation: the dedicated test depends on a Python 3.10+ stack that is not installed in the current execution environment.
- Block 3:
	- files imported: `core/planning/*`, `interfaces/cli/pmv.py`, `tests/test_pddl_planning.py`;
	- validation: Python syntactic compilation passes for all imported files.
- Block 4:
	- files imported: `core/execution/*`, `interfaces/cli/manifest.py`, `interfaces/cli/run.py`, `tests/test_agno_executor.py`;
	- validation: Python syntactic compilation passes for all imported files; the quick regression of existing core remains green (`16 passed`).

## Incorporation Strategy
### Block 1 — static artifacts and documentation
Scope:
- docs/pmv_agno_pddl.md
- schemas/*.json
- core/planning/domains/domain_v2.2.pddl

Validation:
- Existing project tests pass without regressions; JSON schemas are valid.

### Block 2 — structural manifest (PMV 1)
Scope:
- core/manifest/*
- the schema generation script for manifests
- focused processing-manifest tests

Validation:
- Manifest tests pass and compatibility with the current pipeline is preserved.

### Block 3 — PDDL planning (PMV 2)
Scope:
- core/planning/* (processor, planner, schema); planner adapters/Backends (when applicable); planning tests.

Validation:
- Nominal plan generation/verification and causal closure verification.

### Block 4 — execution with Agno + backend comparison (PMV 2.1)
Scope:
- core/execution/*; plan comparison (both backends); execution-report and planning-comparison schemas;
- workflow/executor tests.

Validation:
- planner internal|fast-downward|both flow works correctly, and comparison verdicts are computed (identical/equivalent/different/inconclusive).

### Block 5 — consolidation
Scope:
- Integration with the current CLI/service; dependency and configuration tweaks; final technical cleanup + documentation.

Validation:
- Final test suite pass rate is acceptable; architectural risks and impact are checked.

## Migration safety rules
- Prefer incremental addition over replacing currently running modules. Run validations at the end of each block, and avoid mass changes without an intermediate commit checkpoint.
