# 0021. Execução limitada de chamadas de modelo pertencente à aplicação

Inglês: [English](0021-bounded-model-call-execution.md).

- **Status:** Aceita
- **Data:** 2026-11-15
- **Componentes:** core, serviço
- **Issue:** [#276](https://github.com/A11yDevs/acessilia/issues/276), etapa 2 após o PR #552

## Contexto

Abandonar uma espera de modelo não mata a thread do provider. Essas chamadas
podem esgotar o executor padrão, que `asyncio.run()` aguarda ao sair. Limitar só
os workers do ThreadPoolExecutor mantém sua fila de submissões ilimitada.
Closures canceladas podem, assim, reter imagens, agentes e clientes.

## Decisão

- O core define `ModelCallRunner`; agentes a recebem por composição. O serviço
  mantém uma implementação por processo entre event loops transitórios.
- O serviço passa `ModelCallLimits` explícito a partir de `MODEL_CALL_WORKERS` e
  `MODEL_CALL_MAX_PENDING` na criação. São configurações do processo, não de
  CoreConfig por execução. Os agentes não leem configurações novas (ADR-0016).
- Submeta ao ThreadPoolExecutor no máximo o número de workers. Mantenha trabalho
  adicional admitido numa FIFO limitada e removível. Na capacidade, rejeite
  imediatamente com `ModelCallRejected`, sem acrescentar retries ocultos.
- Copie o contexto por submissão, inclua espera em fila no deadline e verifique
  a expiração antes da inferência. O cancelamento remove closures pendentes.
  Uma chamada abandonada em execução retém capacidade até sua invocação terminar
  e não pode publicar resultado tardio. `ModelCallTimeout` distingue o deadline
  do timeout do próprio provider.
- Preserve prompts, schemas e políticas de retry/degradação nos agentes/pipeline.
  Trabalho bloqueante geral mantém executor e semântica de cancelamento. Pontes
  síncronas de inspeção do core preservam o contexto na thread auxiliar.
- O shutdown da API/CLI fecha admissão, descarta pendências e acorda chamadores
  pendentes e ativos com `ModelCallRejected`, sem aguardar threads de modelo.
  As threads dos providers ativos continuam, retêm suas reservas até terminar e
  têm seus resultados tardios descartados. Não substitua um executor fechado
  enquanto seus workers permanecerem.
  Nem `shutdown(wait=False)` nem fechar um loop mata threads ou garante saída
  imediata do interpretador: Python ainda as aguarda. Um provider permanentemente
  travado pode exigir interrupção externa do processo.
- Logs localizados e snapshots expõem reservas ativas, chamadas pendentes ou
  abandonadas, rejeições, expirações, espera em fila e duração de execução (#385).

No começo, o orquestrador não exigia um runner e obtinha o executor do serviço
quando nenhum era fornecido, como sua ponte de CoreConfig. O passo 3 da
ADR-0016 removeu as duas: `execute(..., config=, model_calls=)` exige o runner
da execução (o passo 4 da ADR-0016 depois acrescentou o `ports=` obrigatório). Chamadores independentes podem passar e fechar seu runner. Os agentes do chat
AgentOS ficam fora desse caminho.
Como um processo conversa com um só provider de modelo (`ModelConfig.ai_client`),
o runner do serviço também é o limite por provider entre execuções: execuções
simultâneas somam o `VISION_CONCURRENCY` das suas etapas, mas nunca passam de
`MODEL_CALL_WORKERS` chamadas no provider (#547). Um limite entre processos ou
máquinas cabe ao gateway. Veja a
[arquitetura](../architecture.pt-br.md).

## Consequências e verificação

Capacidade do Core, `VISION_CONCURRENCY`, vagas do gateway/provider e duração de
todo o job são limites separados. Isso limita retenção local e isola outros
trabalhos. `tests/test_model_call_executor.py` verifica deadlines, cancelamento,
saturação, o limite compartilhado por execuções simultâneas em loops de eventos
separados (#547), retenção de vagas, resultados tardios, `run_blocking` independente,
locales simultâneos, handlers síncronos/loops transitórios e shutdown/reinício com
providers bloqueados por eventos. As suítes de agentes, tabelas e cancelamento
existentes preservam as políticas em torno do mecanismo.
