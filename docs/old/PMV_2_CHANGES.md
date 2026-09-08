# PMV 2.0

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](PMV_2_CHANGES.pt-br.md)

Main changes over the received package:

- `InformationalStructuralAgent` now builds an `agno.agent.Agent` with a
  deterministic extraction tool;
- manifest updated to 1.1.0, with costs and attempts;
- versioned pair `domain_v2.2.pddl` + `domain_description_v2.2.md`;
- Agno `PlannerAgent` and PDDL processor;
- causal closure and mandatory validations;
- internal backend and Fast Downward adapter;
- typed and versioned nominal JSON plan;
- `ExecutorAgent` with an Agno Workflow and one Step per action;
- external confirmation of success and replanning protocol;
- CLI `a11y-pmv`;
- manifest, plan, and report schemas;
- domain, compilation, cost, closure, and workflow tests;
- preservation of `docling==2.0.0` and `docling-core==2.0.0`.
