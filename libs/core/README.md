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

`tests/test_boundary.py` checks the boundary on the package's source, and
`tests/test_smoke.py` checks that the installed package works on its own: CI
installs it from its lock, outside the checkout, and runs the smoke test from
there. Run both with `uv run --extra dev pytest` in this folder (`make test-all`
runs them too).

`examples/table_stage.py` runs the table-structure stage from a script,
with an explicit `CoreConfig` and a model-call runner of its own, and imports
neither the service nor FastAPI (ADR-0016's proof of concept):

```bash
uv run --extra dev python examples/table_stage.py \
  examples/fixtures/tables_manifest.json tables.pdf tables.json
```
