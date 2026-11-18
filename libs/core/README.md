# acessilia-core

Acessilia's core: the PDDL pipeline that plans and executes a document's
accessibility, with its agents, enrichment stages and exporters
([ADR-0016](../../docs/adr/0016-core-package.md)).

It imports nothing from the service (`backend`) or the front ends
(`frontend`), and reads no environment variable. Its caller passes what it
needs:

- a `CoreConfig` per run (`acessilia_core.config`);
- the run's `RunPorts`: the region cache, the job's checkpoints and its
  registry of remote operations (`acessilia_core.ports`);
- the model-call runner (`acessilia_core.agents.model_calls`);
- the process setup, once: the logger, the offered locales and the server
  locale (`acessilia_core.logger`, `acessilia_core.i18n`).

`tests/test_core_boundary.py`, at the repository root, checks the boundary.
