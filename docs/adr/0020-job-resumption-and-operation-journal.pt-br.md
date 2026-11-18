# Retomar um job a partir do seu checkpoint durável

- **Status:** Aceita
- **Data:** 2026-11-14
- **Componentes:** core, Toolbox (pelos identificadores de operação da ADR-0019)
- **Issues:** #407, #380, #409

## Contexto

Um job interrompido por um reinício da API se perde. O `recover_pending_jobs`
(`backend/api/worker.py`) marca como erro um job deixado em `processing`,
nomeando a etapa em que estava, e um documento longo recomeça do zero se o
usuário o enviar de novo. O cache de resultados da Toolbox só ajuda depois que
uma execução termina, e um retry após o reinício usava um `operation_id` novo, de
modo que a Toolbox não conseguia se juntar ao trabalho já feito.

A ADR-0019 definiu `task_id`, `operation_id` e `attempt_id`, fez a Toolbox se
juntar a uma operação conhecida e deixou o diário durável do core para esta
issue. Todas as capacidades que o pipeline de documentos chama são idempotentes
(`execution.idempotent` no contrato da Toolbox, respeitado pelo SDK na #406);
`dataset.sample` é a única capacidade não idempotente e o pipeline de documentos
não a chama. Repetir uma etapa inacabada do pipeline é, portanto, seguro;
repetir uma etapa concluída é apenas desperdício.

## Decisão

### Checkpoints

O core deve gravar um checkpoint JSON por fase do pipeline, em
`DATA_DIR/jobs/<task_id>/checkpoints/`. O core os grava pela porta
`JobCheckpoints` do job, que o serviço vincula ao id da tarefa
(`FileJobCheckpoints`; [ADR-0016](0016-core-package.pt-br.md), passo 4):

| Fase | Gravada quando | Contém |
|---|---|---|
| `media` | `media.inspect` respondeu (ou degradou) | a inspeção e sua configuração |
| `manifest` | a extração estrutural passou pelo limite de páginas, depois conforme cada objeto de enriquecimento termina | o manifesto extraído, mantido atualizado com os objetos já concluídos |
| `enriched` | as etapas de enriquecimento terminaram | o manifesto enriquecido |
| `plan` | um plano foi gerado | o plano, a comparação, o manifesto de origem, a decisão do gate e a contagem de replanejamentos |
| `execution` | após cada passo do plano | o manifesto em trabalho, os resultados dos passos até ali e `replan_required` |

Um checkpoint deve carregar uma versão de esquema e o SHA-256 do seu payload.
Deve ser substituído atomicamente, para que um processo morto no meio da escrita
deixe a versão anterior, nunca uma truncada. Um checkpoint de outra versão, com
hash divergente ou ilegível não pode ser usado para retomar; ele é registrado no
log e o job falha como hoje, em vez de continuar sobre dados que esta versão não
sabe ler.

Checkpoints existem apenas dentro de um job. O benchmark e a CLI chamam o
orchestrator sem task id e não gravam nenhum, mantendo o comportamento atual.

Um checkpoint só é reaproveitado sob a configuração em que foi gravado
(#549). Cada fase registra um digest da configuração das etapas que ela
contém (`run_identity.STAGE_FIELDS`, os campos da identidade de
processamento, portanto sem credenciais): a inspeção de mídia, depois a
extração (as opções de fusão e de documento), o enriquecimento (os modelos e
as opções de visão), o plano (o gate de disponibilidade) e a execução (todas
elas), cada uma com o deployment e os providers da Toolbox. O checkpoint do
manifesto gravado durante o enriquecimento também leva a etapa do
enriquecimento, pois carrega o progresso dele. Uma execução retomada cuja
configuração mudou refaz a primeira fase que contém uma etapa alterada e todas
as fases depois dela, mantém as anteriores e registra no log quais etapas
mudaram. Um checkpoint gravado antes desses digests é reaproveitado com um
aviso, como antes.

Os payloads dos checkpoints são os documentos pydantic que o pipeline já carrega
(`ProcessingManifest`, `NominalPlan`, `PlanningComparison`, passos do
`ExecutionReport`); nenhuma segunda representação é introduzida.

### Recuperação

Na inicialização, o `recover_pending_jobs` deve manter a regra para `cancelling`
(o job vira `cancelled`) e para `queued` (o job volta à fila). Para um job
deixado em `processing`, deve:

1. recolocá-lo na fila quando a retomada estiver habilitada
   (`JOB_RESUME_ON_RESTART`), o upload ainda existir e todos os checkpoints
   forem utilizáveis;
2. em qualquer outro caso, falhá-lo como hoje, com a etapa em que estava;
3. deixar intacto um job que já voltou à fila, para que uma recuperação repetida
   não o enfileire duas vezes nem invalide seu status e seus checkpoints.

Um job recuperado esperando na fila ainda não tem tarefa em memória. Ele deve
continuar cancelável: o cancelamento remove sua entrada na fila, o upload e os
checkpoints, e registra o status terminal como faz para um job apenas na fila.

Um desligamento gracioso não é um cancelamento. A API deve marcar o processo
como em desligamento antes de parar o worker da fila, e um job interrompido deve
manter o registro em `processing`, o upload, os checkpoints e os identificadores
de operação. A inicialização seguinte então o retoma. Apenas um cancelamento
explícito do usuário limpa esse estado.

Uma execução retomada deve restaurar o progresso durável que o job mostra (etapa,
progresso, instante de início), não reenviar o e-mail de confirmação e deixar o
orchestrator carregar a última fase e continuar. Ela não pode mudar a semântica
do executor: a ligação do plano é validada contra o manifesto com que ele foi
planejado, `max_retries=0` e o comportamento de não parar diante de um
`execute-obligation` que falhou continuam, `complete-job` ainda recusa uma
obrigação aberta, o orçamento de replanejamento tem um dono e o `run_blocking`
continua esperando.

A entrega não é checkpointada. Uma retomada depois que o pipeline terminou
reexecuta as exportações locais e da Toolbox a partir do documento canônico
completo; toda exportação é idempotente. O e-mail de confirmação nunca é
reenviado. Uma queda entre enviar o e-mail de resultado e registrar
`email_delivery` ainda pode duplicá-lo, como antes desta ADR.

Os checkpoints devem ser removidos quando o job chega a um estado terminal ou é
cancelado, e varridos pela limpeza periódica após a maior retenção de cache (7
dias), para que um job que desaparece sem estado terminal não deixe dados para
sempre.

### Diário de operações

O core deve manter um mapeamento durável de `(task_id, slot lógico)` para
`operation_id` no mesmo banco SQLite dos registros de job. O registro deve
reutilizar esse id quando a mesma chamada lógica começar de novo, para que uma
fase reexecutada após o reinício nomeie a operação que a Toolbox já conhece e a
Toolbox se junte a ela em vez de executar o provider duas vezes (ADR-0019).

O diário guarda apenas identidade: a Toolbox é dona do estado e do resultado da
operação. Se a Toolbox não retiver mais a operação, a repetição roda sob o mesmo
id, o que é seguro porque o pipeline só nomeia capacidades idempotentes. As
linhas são removidas quando o job termina e varridas após 7 dias.

Os slots cobertos são os que o core já nomeia: o upload do artefato, a extração
primária e a secundária. Ampliar a cobertura para outras chamadas à Toolbox não
muda esta ADR.

## Consequências

- Reiniciar a API durante a extração, o enriquecimento, o planejamento ou a
  execução do plano continua o documento a partir do último checkpoint. Um
  desligamento gracioso mantém o job retomável em vez de marcá-lo como
  cancelado. Uma interrupção dentro de uma fase repete só as chamadas inacabadas
  daquela fase; as etapas de enriquecimento persistem cada objeto concluído, de
  modo que um reinício os pula, e toda operação é idempotente.
- Um job sem checkpoint utilizável falha exatamente como antes, então a mensagem
  de recuperação e o e-mail de falha continuam funcionando para jobs mortos antes
  do primeiro checkpoint.
- O checkpoint é um arquivo sobrescrito por fase, não um histórico crescente.
  Seu tamanho é o do manifesto/plano que ele já contém; o custo é limitado pelo
  número de passos do plano.
- `JOB_RESUME_ON_RESTART=false` restaura o comportamento antigo sem reverter o
  código.
- Um reinício da Toolbox ainda perde os resultados das operações em voo; o core
  mantém o id, mas o retry executa o provider de novo. Não existe diário durável
  de operações entre processos na Toolbox, e esta ADR não promete um.
- O diário acrescenta uma tabela ao `history.db`; os checkpoints acrescentam um
  diretório por job em `DATA_DIR`. A limpeza é dona dos dois.
- A conformidade é verificada por `tests/test_job_resume.py` (integridade dos
  checkpoints, recuperação, continuação do executor, progresso restaurado e o
  diário reutilizado após um reinício simulado) e pelas suítes existentes de
  cancelamento, fila e executor, que devem passar sem mudanças.

## Referências

- #407 (este trabalho), #380 e #409 (identificadores de operação e cancelamento,
  ADR-0019), #406 (retry só de capacidades idempotentes), #350 (prazo local da
  extração).
