# PMV 2.1

Mudanças sobre o PMV 2.0:

- seleção `--planner internal|fast-downward|both`;
- compilação única do manifesto no modo `both`;
- planos separados por backend e plano preferido compatível com o Executor;
- comparação estrutural, causal, de métodos, custo e ordem;
- vereditos `identical`, `equivalent`, `different` e `inconclusive`;
- preservação do plano disponível quando o outro backend falha;
- métricas de tempo e estatísticas publicadas pelo Fast Downward;
- validação nominal fortalecida para ambos os backends;
- novo `planning_comparison.schema.json`;
- testes com adaptador Fast Downward controlado e CLI completa;
- compatibilidade preservada com Agno 2.8.5, Docling 2.0.0 e macOS.
