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
  está fora de um plano: `outside-plan` registra exclusão do escopo, inclusive
  trabalho esgotado e metas bloqueadas por dependências esgotadas; não promete
  elegibilidade futura. `failure-budget-exhausted` é mais específico: a meta
  seria replanejável, mas a política de descoberta a exclui ou exclui sua
  predecessora que falhou. Esgotamento por si só nunca recebe esse motivo.
  `replan_roots` recalcula os motivos a cada decisão de política, mesmo sem
  raízes. Entre decisões, a explicação mais recente persiste, inclusive na
  retomada. Selecionar ou satisfazer a meta limpa o motivo. As fronteiras de
  leitura e serialização normalizam motivos em obrigações satisfeitas ou
  fora das metas; falhas legadas sem seleção continuam sendo metas abertas.
- Checkpoints sem o novo campo continuam legíveis. Para obrigações ainda
  presentes, o executor recupera flags apagadas **somente se o manifesto de
  planejamento as preserva** (como no fixture real de 0.3.26). Se ambos os
  manifestos já perderam uma meta, ela é indistinguível de trabalho
  intencionalmente não selecionado; este PR não pode reconstruí-la. A
  recuperação depende do estado registrado, não só da versão do pacote.
  Um motivo ausente é omitido da serialização, preservando hashes e vínculos.
  Motivos presentes continuam fazendo parte do manifesto persistido e do hash.

## Consequências

O orquestrador deixa de precisar de `_restore_goals`. Um plano pode terminar
seu escopo enquanto a entrega ainda falha ou degrada por outra meta aberta.
Não há outra fonte de verdade para metas nos serviços da execução.
Excluir uma meta de um plano parcial nunca a cancela. `selected=False` por
si só não é uma transição de cancelamento: a retomada pode recuperar a flag
do planejamento. Uma obrigação obsoleta ainda pode ser removida. Cancelamento
explícito persistido e eventual renomeação de `selected` ficam na
[#909](https://github.com/A11yDevs/acessilia/issues/909).

### Exceção delimitada ao versionamento do contrato

Esta decisão estende deliberadamente o processing-manifest:1.1.0 do core sem
alterar seu id, como exceção aos requisitos de versionamento e conformidade
da [ADR-0007](0007-manifest-model-and-mathml-conversion.pt-br.md) e do achado
A1 da auditoria. Escopo: metadados opcionais de planejamento do core, omitidos
quando ausentes, preservando hashes históricos. O validador do core é dono
dessa extensão; o schema da Toolbox e o `MANIFEST_RULE` gerado do SDK
continuam estritos e não aceitam `deferred_reason`. Um checkpoint do core
com esse campo não é um payload de documento estruturado da Toolbox; cores
antigos não precisam lê-lo.

Responsáveis: mantenedores do core, em coordenação com os donos dos contratos
do SDK e da Toolbox. Critério de saída: contrato versionado distinto ou
migração para o envelope de planejamento do core, adapters explícitos e
testes entre contratos na [#908](https://github.com/A11yDevs/acessilia/issues/908).
Esta exceção não autoriza novas divergências silenciosas de schema.

`test_job_goals.py` verifica planos parciais, execução posterior, metas
removidas e um fixture real do plano e da execução de 0.3.26 com proveniência
e hash original. `test_discovery_after_failure_budget.py`
verifica política de entrega, motivos de adiamento e retomada de checkpoints
atuais e antigos.
