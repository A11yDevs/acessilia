# PMV 2.0

Principais mudanças sobre o pacote recebido:

- `InformationalStructuralAgent` agora constrói um `agno.agent.Agent` com
  ferramenta determinística de extração;
- manifesto atualizado para 1.1.0, com custos e tentativas;
- par versionado `domain_v2.2.pddl` + `domain_description_v2.2.md`;
- `PlannerAgent` Agno e processador PDDL;
- fechamento causal e validações obrigatórias;
- backend interno e adaptador Fast Downward;
- plano nominal JSON tipado e versionado;
- `ExecutorAgent` com um Agno Workflow e um Step por ação;
- confirmação externa de sucesso e protocolo de replanejamento;
- CLI `a11y-pmv`;
- schemas de manifesto, plano e relatório;
- testes de domínio, compilação, custo, fechamento e workflow;
- preservação de `docling==2.0.0` e `docling-core==2.0.0`.
