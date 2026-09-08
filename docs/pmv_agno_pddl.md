# PMV 2.1 — Agno, manifest, PDDL, comparison and nominal execution

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](pmv_agno_pddl.pt-br.md)

## Purpose

This release validates the minimal cycle:

```text
document
  → Informational-Structural Agent (Agno + Docling)
  → processing-manifest.json
  → Planner Agent (Agno + PDDL tools)
  → problem.pddl
  → nominal-plan.json
  → Executor Agent (Agno Workflow)
  → execution-report.json + revised manifest
```

Agno coordinates the tools and the workflow. Extraction, problem compilation,
contract validation and effect application are deterministic functions.
No LLM writes PDDL directly.

## macOS compatibility

- Python 3.11 or 3.12;
- `docling==2.0.0`;
- `docling-core==2.0.0`;
- `agno==2.8.5`;
- Fast Downward optional.

```bash
poetry lock
poetry install
poetry run python scripts/generate_pmv_schemas.py
poetry run pytest
```

The previous lock file was produced before Agno was added and does not include the new
package. Regenerate it on your own macOS machine; the critical Docling and Agno versions
are already pinned in `pyproject.toml`.

Fast Downward is only required when using `--planner fast-downward` or
`--planner both`. The `internal` backend is the PMV's reference planner and works
without any external binary.

## 1. Informational-Structural Agent

`InformationalStructuralAgent` builds an `agno.agent.Agent` with the tool
`extract_processing_manifest`. The Python method `process()` uses the same
deterministic implementation, which allows testing without an LLM call.
An Agno model can be injected via the `model` argument; the CLI needs no API key
because it invokes the deterministic tool directly.

```bash
poetry run a11y-pmv manifest document.pdf \
  -o output/processing-manifest.json \
  --no-ocr
```

Manifest 1.1 adds to each obligation:

- the admissible methods;
- a non-negative integer cost per method;
- the observed attempts;
- the outcome of every attempt.

The file is only persisted after it passes the Pydantic model and JSON
Schema Draft 2020-12.

## 2. Planner Agent and PDDL processor

`PlannerAgent` loads an inseparable pair:

- `core/planning/domains/domain_v2.2.pddl`;
- `core/planning/domains/domain_description_v2.2.md`.

The loader checks version, name, hashes and mandatory clauses. The compiler:

1. picks the root obligations;
2. computes the transitive closure of their predecessors;
3. projects state, types, dependencies, methods, attempts and costs;
4. generates `problem.pddl`;
5. requires `(:metric minimize (total-cost))`;
6. validates the projection before invoking any planner.

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output
```

By default, obligations already marked as `selected` are the roots. If none are
marked, all unsatisfied obligations are selected. To choose specific roots:

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output \
  --select obligation-describe-image-000012
```

### Backends

Internal planner:

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output \
  --planner internal
```

Fast Downward:

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output \
  --planner fast-downward \
  --fast-downward /path/to/fast-downward.py \
  --fast-downward-search 'astar(blind())'
```

`astar(blind())` is the conservative default because it preserves costs and supports
domain axioms/derived predicates. An alias can be given explicitly with
`--fast-downward-alias`, as long as its heuristics support the features of domain 2.2.

The internal backend is not meant to replace a general-purpose planner. It exploits
the specific structure of domain 2.2: it sorts the obligations DAG and picks the
cheapest admissible, never-tried method. It is a simple, reproducible oracle for
validating the PMV.

### Running both backends

For differential studies:

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output \
  --planner both \
  --fast-downward /path/to/fast-downward.py \
  --fast-downward-search 'astar(blind())' \
  --preferred-plan internal
```

The domain is loaded once and the manifest compiled once, so both backends receive
the exact same bytes of `domain_v2.2.pddl` and `problem.pddl`, identified by SHA-256.

The outputs are:

```text
output/
├── problem.pddl
├── nominal-plan.internal.json
├── nominal-plan.fast-downward.json
├── nominal-plan.json
└── planning-comparison.json
```

`nominal-plan.json` is a logical copy of the backend defined by `--preferred-plan`
and can be supplied directly to the Executor. The default is `internal`; use
`--preferred-plan fast-downward` to run the Fast Downward plan.

If only one backend solves the problem, its plan is still preserved and the report
receives the verdict `inconclusive`. The command stops producing the canonical plan
only when exactly the preferred backend fails.

## 3. Comparison for studies

Before comparison, each plan passes independent validation of:

- domain and problem identity and hashes;
- closure of the selected obligations;
- preconditions and causal order;
- an admissible, available and not-yet-tried method;
- the type and cost of every obligation;
- termination in `complete-job`.

The report distinguishes four verdicts:

| Verdict | Meaning |
|---|---|
| `identical` | same actions, parameters, methods, costs and order |
| `equivalent` | same semantic content and cost, differing only in the order between independent actions |
| `different` | both solve, but cost, methods, actions or closure diverge |
| `inconclusive` | at least one backend did not produce a valid plan |

Beyond the verdict, `planning-comparison.json` records:

- wall time per backend;
- configuration and statistics published by Fast Downward;
- total cost and number of steps;
- closure equality and executed obligations; methodology agreement between backends;
- method selection equality;
- action sequence and action-multiset equality;
- the cost delta in the direction Fast Downward minus internal;
- each result's exclusive steps; error type and message, when applicable.

A costly coincidence match is not treated as equivalence. Conversely, an order
difference between causally independent obligations is not mistakenly classified as a
divergence.

## 4. Nominal JSON plan

The plan contains:

- domain and description identity and hashes;
- manifest identity, revision and hash; problem.pddl hash; planning backend; selected closure;
- total expected cost;
- typed, ordered actions.

The effect of `execute-obligation` means success in the nominal model. The Executor
only confirms that effect after the handler returns both `success=true` and
`validated=true`.

## 5. Executor Agent with Agno Workflow

Each action in the plan becomes an `agno.workflow.Step`. The Workflow executes steps
in sequence and stops on the first error.

Dry-run, without confirming effects:

```bash
poetry run a11y-pmv execute \
  output/processing-manifest.json \
  output/nominal-plan.json \
  -o output/execution
```

Real execution requires handlers:

```bash
poetry run a11y-pmv execute \
  output/processing-manifest.json \
  output/nominal-plan.json \
  -o output/execution \
  --live \
  --handler-module meu_projeto.handlers
```

The module must provide:

```python
from core.execution.models import MethodResult


def describe_image(manifest, obligation_id):
    # invokes the tool, validates the result and produces artifacts
    return MethodResult(
        success=True,
        validated=True,
        message="Validated description",
        artifacts=[],
    )


def register_handlers(registry):
    registry.register("vision-description", describe_image)
```

`examples.demo_handlers` lets you exercise the `--live` path, but it is explicitly
simulated and must not be used in production.

On failure:

- the attempt is recorded in the manifest; the effect `satisfied` is not confirmed;
- the report flags a failure or `replan-required`; a fresh compilation emits `(tried obligation method)`;
- the planner picks an alternate, when any remains.

## 6. End-to-end execution

```bash
poetry run a11y-pmv pipeline document.pdf \
  -o output/job-001 \
  --no-ocr \
  --planner both \
  --fast-downward /path/to/fast-downward.py \
  --preferred-plan internal \
  --execute-dry-run
```

Key outputs:

```text
output/job-001/
├── processing-manifest.json
├── problem.pddl
├── nominal-plan.json
├── nominal-plan.internal.json
├── nominal-plan.fast-downward.json
├── planning-comparison.json
├── manifest-after-execution.json
└── execution-report.json
```

## 7. Versioned contracts

| File | Contract |
|---|---|
| `processing_manifest.schema.json` | structure, observations, obligations, costs and attempts |
| `nominal_plan.schema.json` | auditable nominal plan |
| `planning_comparison.schema.json` | the outcome of both planners' comparison, normalized |
| `execution_report.schema.json` | observed steps and replan decision |
| `domain_v2.2.pddl` | general action and cost semantics |
| `domain_description_v2.2.md` | human contract and compiler rules |

The three JSON Schemas are generated from the Pydantic models:

```bash
poetry run python scripts/generate_pmv_schemas.py
```

CI must fail if any generated file diverges from the versioned schemas.

## PMV limitations

- one document/job per PDDL instance; the internal planner covers only the 2.2 obligations domain;
- the comparison covers plans and metrics published by both backends, not artifact quality at runtime;
- description, linearization, verbalization and export methods still need registration in real form;
- the workflow halts after a failure and returns state to the Planner; the automatic replan loop is left for the next iteration.
