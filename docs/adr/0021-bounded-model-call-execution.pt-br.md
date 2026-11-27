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
  pendentes e ativos com `ModelCallClosed`, sem aguardar threads de modelo.
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
O processo do serviço conversa com um só provider de modelo (o seu `AI_CLIENT`),
então o runner do serviço também é o limite por provider entre execuções:
execuções simultâneas somam o `VISION_CONCURRENCY` das suas etapas, mas nunca
passam de `MODEL_CALL_WORKERS` chamadas no provider (#547). Um chamador
independente que roda várias `ModelConfig` num processo com um só runner
divide esse limite entre os providers delas, o que é mais restrito, nunca mais
frouxo. Um limite entre processos ou máquinas fica fora do core: com
`AI_CLIENT=toolbox`, cabe ao gateway da Toolbox; Ollama e OpenRouter não têm um
gateway nosso, então valem os limites deles. Veja a
[arquitetura](../architecture.pt-br.md).

Desdobramento (#590). A concorrência da fila e o `VISION_CONCURRENCY` se
multiplicam: `jobs simultâneos × VISION_CONCURRENCY` chamadas podem chegar
juntas, e o runner precisa admiti-las ou rejeitar o excesso. Mantendo a rejeição
imediata acima, o serviço deriva `MODEL_CALL_MAX_PENDING` desse produto quando a
variável não está definida ou vale -1 (no mínimo os 4 históricos) e avisa no startup, sem
recusá-lo, quando um valor explícito não cobre os jobs configurados. O aviso
nomeia a capacidade pendente exata que fecha a lacuna. Ficar acima da capacidade
é um modo degradado, não inseguro, e as etapas podem usar menos chamadas que seu
limite. A fórmula pressupõe que os subplanos de enriquecimento de um job sejam
sequenciais, de modo que um limite de etapa valha por vez; subplanos paralelos
exigiriam um novo orçamento agregado (#828). Dimensionar a capacidade de admissão
não torna a execução de vários jobs segura, por isso `QUEUE_MAX_CONCURRENT` acima
de 1 continua atrás do opt-in explícito `QUEUE_MULTI_JOB_EXPERIMENTAL=true` até
que a #238 W1 forneça a justiça por origem, a API pública de cancelamento e as
decisões de isolamento de memória/falhas (#830). A validação da configuração, a
fábrica e o construtor da fila aplicam a mesma invariante.

Uma rejeição é pressão de admissão, não saúde do provider. Ela é tentada uma vez
de novo, como um timeout, sem consumir uma tentativa de resposta; se persistir, a
etapa registra `admission_rejected` (imagens, tabelas, fórmulas), deixa o breaker
compartilhado intacto e mantém a execução fora do cache para que uma nova
execução a retente. Um runner fechado gera o subtipo `ModelCallClosed`: é
ciclo de vida, não pressão de capacidade, então os agentes não o retentam e as
etapas abortam em vez de registrar uma degradação recuperável. O fechamento
também acorda chamadores pendentes e ativos com o mesmo subtipo.

Composição dos retries (revisão da #590). Os orçamentos são independentes e
limitados: um retry de admissão por chamada do agente, um retry de timeout, dois
retries de rate limit e as tentativas de resposta/validação dentro do agente;
depois, a passada coletiva `_retry_failed` dá a cada imagem/tabela falha mais uma
tentativa após `VISION_RETRY_PASS_DELAY_SECONDS`; uma tabela mal lida tem seu
próprio orçamento de releituras. Uma rejeição de admissão não cria espera por
tabela, não consome tentativa de resposta e não abre o breaker.

## Consequências e verificação

Capacidade do Core, `VISION_CONCURRENCY`, vagas do gateway/provider e duração de
todo o job são limites separados. Isso limita retenção local e isola outros
trabalhos. `tests/test_model_call_executor.py` verifica deadlines, cancelamento,
saturação, o limite compartilhado por execuções simultâneas em loops de eventos
separados (#547), retenção de vagas, resultados tardios, `run_blocking` independente,
locales simultâneos, handlers síncronos/loops transitórios e shutdown/reinício com
providers bloqueados por eventos. `tests/test_model_call_capacity.py` e
`libs/core/tests/test_model_call_admission.py` cobrem a verificação de
dimensionamento e a semântica de rejeição/razão da #590. As suítes de agentes,
tabelas e cancelamento existentes preservam as políticas em torno do mecanismo.
