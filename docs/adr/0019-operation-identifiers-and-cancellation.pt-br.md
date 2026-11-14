# Identificadores de operação e cancelamento remoto

Status: Aceita

## Contexto

Um job pode executar várias chamadas remotas à Toolbox: um upload de
artefato, uma extração estrutural primária e, na fusão dupla, uma extração
secundária. Hoje nenhuma delas pode ser nomeada. Quando o usuário cancela um
job, o core pode parar de esperar no prazo da extração
(`TOOLBOX_EXTRACTION_TIMEOUT_SECONDS`, #350), mas a Toolbox mantém a thread do
provider executando e o slot de execução ocupado.

Retries e failover tornam um identificador de requisição insuficiente: um
timeout de leitura não diz ao cliente se a primeira requisição executou, e
dois endpoints independentes da Toolbox não compartilham deduplicação. A mesma
decisão é necessária para a retomada (#407) e para a observabilidade (#385). A
constituição exige ADR para um contrato que atravessa core, SDK e Toolbox, e a
#380 pediu essa decisão antes da implementação.

## Decisão

### Identificadores

- **`task_id`** identifica um job do core. O core o gera (o id do job já
  visível na API) e o mantém durante todo o job. Ele não é reutilizado por
  outro job.
- **`operation_id`** identifica uma operação remota lógica: um upload de
  artefato ou uma invocação de capacidade. O core gera um UUIDv4 novo para
  cada operação. Ele permanece o mesmo entre retries e failover do SDK para
  aquela operação.
- **`attempt_id`** identifica uma tentativa HTTP. O SDK gera um UUIDv4 novo
  imediatamente antes de cada requisição, incluindo cada retry e cada endpoint
  tentado. Ele muda mesmo quando o `operation_id` não muda.

Os identificadores trafegam em cabeçalhos, não no formulário da capacidade nem
no contrato publicado:

```text
X-Acessilia-Task-Id: <task_id>
X-Acessilia-Operation-Id: <operation_id>
X-Acessilia-Attempt-Id: <attempt_id>
```

Eles são opcionais por compatibilidade. Um chamador que os omite mantém o
comportamento antigo: sem registro e sem cancelamento remoto. Quando há um
`operation_id`, o `task_id` é obrigatório. Os identificadores têm 1–200
caracteres seguros para log (`[A-Za-z0-9][A-Za-z0-9._:-]*`); um identificador
obrigatório ausente ou inválido é `400 invalid_input`, antes de qualquer
provider executar.

### Escopo e autenticação

O cancelamento usa a chave de API existente da Toolbox. O endpoint exige
`operation_id` e `task_id` e responde `404 operation_not_found` quando o par é
desconhecido ou pertence a outra tarefa. Ele nunca revela se outro job é dono
do id. Não há cancelamento entre tarefas, e o core nunca envia identificadores
de outro job.

### Estados da Toolbox

A Toolbox mantém um registro local ao processo enquanto a operação executa:

| Estado | Significado |
|---|---|
| `running` | A requisição é dona da execução do provider ou espera por ela. |
| `cancel_requested` | Um pedido de cancelamento encontrou a operação. É um reconhecimento, não a prova de que o provider parou de calcular. |
| `cancelled` | A requisição observou o pedido antes de publicar um resultado. Nenhum resultado é armazenado, cacheado ou devolvido. |
| `finished` | A requisição terminou antes de um pedido de cancelamento ser observado. |
| `failed` | A requisição falhou antes de um pedido de cancelamento ser observado. |

`POST /v1/operations/{operation_id}:cancel` devolve o estado atual. Uma
operação em execução passa a `cancel_requested`; uma operação terminal mantém
seu estado. O cancelamento é idempotente: repetir o pedido é permitido e
devolve o mesmo estado. Um `operation_id` duplicado com o mesmo `task_id` se
junta à operação em execução ou terminal em vez de executar o provider de
novo; é isso que impede um retry idempotente de rodar duas vezes. A resposta
concluída (ou o erro) é mantida apenas enquanto o registro local ao processo a
retiver.

Para um provider interrompível, o cancelamento fecha ou aborta a requisição
upstream. Um provider em processo pode apenas verificar uma flag cooperativa.
Trabalho que não pode ser interrompido pode terminar, mas seu resultado é
descartado e nunca é armazenado, cacheado, publicado ou devolvido. O slot de
execução é liberado quando a thread realmente termina, não quando o endpoint
de cancelamento responde; por isso a resposta distingue `cancel_requested` de
`cancelled`.

### Comportamento do core

Quando o usuário cancela um job, o core:

1. registra o cancelamento local imediatamente, como hoje;
2. pede à Toolbox para cancelar cada operação ativa do job, com um único
   orçamento curto de parede (`TOOLBOX_CANCEL_TIMEOUT_SECONDS`, padrão 5 s);
3. registra um estado de melhor esforço no job: `none`, `requested`,
   `finished`, `not_found` ou `failed`;
4. mantém o `run_blocking` esperando a thread de extração, como hoje.

Um pedido de cancelamento que falha ou expira é registrado no log e no status;
não é erro, retry da capacidade original, failover, busca de download nem
reenvio da entrada. Ele não atrasa a API além do orçamento configurado. O job
local ainda pode chegar a `cancelled` quando o prazo da extração terminar.

`cancelled` no core significa que o job local terminou. Isso não afirma, por
si só, que o provider parou; apenas uma leitura de estado da Toolbox ou uma
execução confirmada como `cancelled` faria isso. O core relata `requested` em
vez de prometer um aborto remoto.

## Consequências

- Os identificadores de operação são um contrato aditivo da API da Toolbox.
  Versões antigas ignoram os cabeçalhos e respondem `404` ao cancelamento; o
  core relata `not_found` ou `failed` e continua funcionando.
- O registro é em memória e por processo. Com endpoints independentes ou um
  balanceador que não encaminhe o cancelamento à réplica dona da operação, o
  cancelamento pode responder `not_found`. Um diário durável e compartilhado é
  a #407, não esta ADR.
- Após reinício da Toolbox ou do core, operações em voo se perdem do registro.
  A recuperação mantém a regra atual: um job deixado em `cancelling` vira
  `cancelled`, e o trabalho remoto fica sujeito aos timeouts configurados.
- Um retry que se junta a uma operação pode esperar tanto quanto a requisição
  dona; ele não consome um segundo slot. O cancelamento do dono se propaga às
  tentativas que se juntaram.
- Identificadores de operação não são chave de cache e não mudam resultados,
  política de retry ou failover. Eles apenas identificam e, quando possível,
  param uma operação.
- O core anexa identificadores ao upload, à extração primária e à secundária.
  Outras chamadas à Toolbox mantêm o comportamento antigo até receberem um
  dono de operação; ampliar a cobertura não muda este contrato.
- O cancelamento remoto é de melhor esforço. Trabalho que um provider não
  consegue interromper continua ocupando seu slot até terminar, mesmo que o
  resultado seja descartado.

## Referências

- #350 (prazo local da extração), #407 (retomada e operações repetidas),
  #409 (este cancelamento), #380 (identificadores de operação), #406 (retry
  só de capacidades idempotentes).
- Issues da Toolbox #146 (quem pode agir sobre uma operação) e #137 (ciclo de
  vida de sidecars).
