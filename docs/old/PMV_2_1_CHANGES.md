# PMV 2.1

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](PMV_2_1_CHANGES.pt-br.md)

Changes over PMV 2.0:

- `--planner internal|fast-downward|both` selection;
- single manifest compilation in `both` mode;
- separate plans per backend and a preferred plan compatible with the Executor;
- structural, causal, method, cost, and order comparison;
- `identical`, `equivalent`, `different`, and `inconclusive` verdicts;
- preservation of the available plan when the other backend fails;
- time metrics and statistics published by Fast Downward;
- strengthened nominal validation for both backends;
- new `planning_comparison.schema.json`;
- tests with a controlled Fast Downward adapter and the full CLI;
- compatibility preserved with Agno 2.8.5, Docling 2.0.0, and macOS.
