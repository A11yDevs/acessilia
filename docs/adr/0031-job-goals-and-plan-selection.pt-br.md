# 0031. Metas do job sobrevivem à seleção de um plano

Inglês, versão normativa: [English version](0031-job-goals-and-plan-selection.md).

- **Status:** Aceita
- **Data:** 2026-11-26
- **Componentes:** core
- **Issues:** [#883](https://github.com/A11yDevs/acessilia/issues/883), [#640](https://github.com/A11yDevs/acessilia/issues/640)

## Contexto

A flag `selected` de uma obrigação representava tanto uma meta do job quanto
sua participação no plano atual. Um plano de descoberta depois de esgotado
o orçamento de falhas atende apenas ao trabalho independente. Apagar as
outras metas escondia falhas da verificação de entrega. A #882 restaurava as
flags depois de cada execução, mas os checkpoints de execução ainda
registravam a perda temporária das metas.

## Decisão

- `Obligation.selected` registra uma meta do job. Executar um plano não deve
  apagar essa flag nas metas fora do seu escopo. As obrigações descobertas
  por um handler bem-sucedido continuam virando metas; as removidas ficam
  removidas.
- `NominalPlan.selected_obligations` registra o escopo do plano atual,
  incluindo dependências. `complete-job` confere esse escopo e as metas
  recém-descobertas. A verificação final de entrega julga todas as metas
  abertas, mesmo quando o último plano terminou. Continuam valendo as
  políticas existentes de criticidade e cache.
- O campo opcional `Obligation.deferred_reason` registra por que uma meta
  está fora do plano atual: `outside-plan` para uma seleção parcial ou
  `failure-budget-exhausted` para trabalho que falhou e seus dependentes
  excluídos pela política de descoberta. O payload de obrigações
  insatisfeitas inclui o motivo quando presente. Selecionar a meta em um
  plano posterior limpa seu adiamento.
- Checkpoints de 0.3.x continuam legíveis. Para obrigações ainda presentes,
  o executor usa o manifesto de planejamento para recuperar flags de meta
  apagadas pelo executor antigo. Um adiamento ausente assume `None` e é
  omitido da serialização, preservando hashes e vínculos dos planos antigos.
  Motivos presentes continuam fazendo parte do manifesto persistido e do hash.

## Consequências

O orquestrador deixa de precisar de `_restore_goals`. Um plano pode terminar
seu escopo enquanto a entrega ainda falha ou degrada por outra meta aberta.
Não há outra fonte de verdade para metas nos serviços da execução.
O campo é uma adição ao schema 1.1.0; cores antigos não precisam ler novos
checkpoints que o contenham.

`test_job_goals.py` verifica planos parciais, execução posterior, metas
removidas e hashes antigos estáveis. `test_discovery_after_failure_budget.py`
verifica política de entrega, motivos de adiamento e retomada de checkpoints
atuais e antigos.
