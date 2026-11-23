# A projeção do estado observado em PDDL (#640, PR 1)

Inglês, versão normativa: [English version](pddl-state-projection.md)

A [ADR-0029](../adr/0029-symbolic-core-every-step-planned.pt-br.md) compila
cada problema de planejamento a partir do estado observado: os fatos do
manifesto, as obrigações, os resultados já registrados e um snapshot do
catálogo. Esta página documenta o que `PddlProblemCompiler.compile`
(`planning/pddl_processor.py`) projeta hoje, para o domínio v2.4, e o que
ainda falta. `libs/core/tests/test_pddl_state_projection.py` tem um teste por
regra, então uma mudança na projeção aparece no diff.

## Entradas

`compile(manifest, *, selected_roots=None, unavailable_methods=(), catalogue=None)`. O
orquestrador o chama pelo `PlanningEngine` (#744), com um `PlanningProblem`:

- `manifest`: o manifesto de processamento, como observado até agora;
- `selected_roots`: as obrigações a planejar, ou `None` (veja abaixo);
- `unavailable_methods`: os métodos que o plano não pode usar: os que não
  têm handler registrado. Um checkpoint de plano anterior ao domínio 2.4
  também traz os métodos que o gate excluía pelo nome;
- `catalogue` (`CatalogueFacts`, domínio 2.4): o snapshot do catálogo da
  Toolbox, como os requisitos de cada método (capacidade, provider) e o que o
  snapshot oferece. O gate de disponibilidade o monta (`catalogue_facts()`).

## Regras

| Estado observado | PDDL | Observações |
|---|---|---|
| Status do manifesto `extracted` ou `planned` | `(queued)` | O plano começa com `start-job` |
| Qualquer outro status (`processing`, `failed`) | `(processing)` | Um replanejamento continua o job |
| Status do manifesto `completed` | recusado (`ValueError`) | Um job concluído não é planejado |
| — | `(= (total-cost) 0)`, objetivo `(completed)`, métrica `minimize (total-cost)` | Todo problema |
| Raízes: `selected_roots`; sem elas, as obrigações marcadas `selected`; sem essas, toda obrigação não `satisfied` | — | Uma raiz desconhecida é recusada |
| As raízes e suas `dependencies` transitivas | um objeto `obligation` e `(selected o)` para cada | Obrigações fora do fecho não são projetadas |
| `kind` da obrigação | `(kind-of o k)`, um objeto `obligationkind` | |
| Status `satisfied` | `(satisfied o)` | |
| Qualquer outro status (`candidate`, `pending`, `in_progress`, `failed`) | `(pending o)` | Uma obrigação `failed` com um método não tentado ainda pode ser planejada |
| `dependencies` | `(depends-on o predecessora)` | |
| Cada método admissível | `(supports m k)`, `(admissible m o)` | `supports` vem dos métodos admissíveis do manifesto, não de um catálogo |
| `method_costs[m]` | `(= (execution-cost m o) custo)` | 50 quando o manifesto não declara custo |
| Um método fora de `unavailable_methods` | `(available m)` | O Core tem um handler para ele |
| Os requisitos de catálogo de um método | `(requires m c p)`, objetos `capability` e `provider` | Só para os métodos deste problema; um método sem requisitos não tem nenhum |
| Os pares exigidos que o snapshot oferece | `(offered c p)` | Gate em `observe` ou `off`: todo requisito é oferecido, então o plano não muda. `enforce`: o que o snapshot publica numa versão compatível; nada sem snapshot (falha fechada) |
| — | `(runnable m)`, derivado pelo domínio | `available` e todo requisito oferecido. `execute-obligation` o exige |
| Uma tentativa `failed` ou `rejected` | `(tried o m)` | Uma tentativa `succeeded` não é projetada; seu resultado é o status da obrigação. Uma tentativa `failed` descarta o método para aquela obrigação, qualquer que seja a causa (veja abaixo) |
| Ids, kinds e nomes de métodos | símbolos PDDL (`[a-z][a-z0-9-]*`) | A projeção guarda o mapeamento nos dois sentidos |

Fatos duplicados são emitidos uma única vez. O problema não depende da ordem
das obrigações nem dos seus métodos no manifesto, e ids distintos que se
normalizam no mesmo símbolo recebem símbolos distintos (um sufixo de hash).

Um conjunto vazio de raízes, ou um manifesto sem obrigações, não projeta
nenhuma obrigação: o plano é `start-job`, `complete-job`.

## O que não é projetado

- O documento em si: elementos, texto, alvos, observações e artefatos ficam
  no manifesto. O plano nomeia só obrigações e métodos.
- Obrigações fora do fecho selecionado.
- Tentativas bem-sucedidas e os resultados dos métodos, exceto pelo status da
  obrigação.

## Verificações

O compilador recusa um problema que não consegue planejar, antes de o
planejador rodar:

- **Estado causal.** Uma obrigação satisfeita com uma predecessora
  insatisfeita. O modelo do manifesto também recusa esse estado; o
  compilador verifica de novo porque um replanejamento altera o manifesto no
  lugar.
- **Métodos.** Uma obrigação pendente sem método admissível, executável
  (`runnable`) e não tentado.
- **Catálogo v2.3.** Para um kind do catálogo v2.3, métodos admissíveis fora
  dele, ou um método sem custo.
- **Métodos indisponíveis desconhecidos.** Um método indisponível que o
  manifesto não declara: um erro de digitação, não uma lacuna de capacidade.
- **Dependências.** Uma dependência de uma obrigação desconhecida, ou um
  ciclo no fecho selecionado, nomeando as obrigações. O modelo do manifesto
  também recusa os dois; o compilador verifica de novo porque um
  replanejamento altera o manifesto no lugar, e assim todo backend de
  planejamento falha do mesmo jeito
  ([#783](https://github.com/A11yDevs/acessilia/issues/783)).
- **O problema renderizado.** O `PddlProblemValidator` o confere contra a
  projeção.

## Identidade

- `CompiledProblem.sha256` é o hash do texto do problema. Ele muda
  exatamente quando o estado projetado muda, e o plano o registra
  (`problem_sha256`). O coordenador o confere desde o #744.
- `manifest_sha256` é o hash do manifesto inteiro, inclusive do que não é
  projetado.
- A identidade do checkpoint de planejamento inclui os hashes do domínio. O
  executor recusa um plano feito com outro domínio, então, depois de uma
  mudança de domínio (2.3 → 2.4), um job retomado planeja de novo em vez de
  falhar.
- São identidades diferentes. Dois manifestos que diferem só fora da
  projeção (o texto de um elemento, uma observação) produzem o mesmo
  problema, então `problem_sha256` é a identidade do estado de
  planejamento, nunca do estado documental. Checkpoints, contratos de
  delegação e replanejamento guardam as duas.

## Limitação conhecida: o que `tried` significa

`tried` vem de qualquer tentativa `failed` ou `rejected`, então um método que
falhou por um motivo transitório (timeout, provider fora do ar, erro de
infraestrutura) é descartado para aquela obrigação como um que não conseguiu
satisfazê-la. O ciclo fechado precisa distinguir:

- falha semântica: o método rodou e não satisfez a obrigação;
- rejeição: o resultado não atendeu aos critérios;
- falha transitória: timeout, provider indisponível, infraestrutura;
- falha permanente: a capacidade é incompatível ou não pode executar a
  operação.

Nem todas devem impedir uma nova tentativa do mesmo método. Isso pertence
aos contratos de resultado, ao journal de execução e às regras de
replanejamento da #640 (PRs 3 e 4). Esta página documenta o comportamento
atual.

## O que a ADR-0029 ainda pede

| ADR-0029 | Hoje | Próximo |
|---|---|---|
| A disponibilidade de capacidades e providers é predicado do problema | Feito no domínio 2.4: `requires`, `offered` e o derivado `runnable` | — |
| O `toolbox_gate` vira só relatório | Ele ainda decide o que é oferecido no `enforce` | #640, PR 2: o snapshot em si é a entrada, e o `observe` sai |
| Ações operacionais ligadas a um id de capacidade e versão exata | Os métodos nomeiam handlers locais | #640, PR 2, com os fragmentos de domínio |
| Um resultado atualiza o estado uma vez por `operation_id` | Os status e as tentativas do manifesto | #640, PR 3, com o journal da ADR-0020 |
| Inspeção, extração e enriquecimento são ações | Rodam antes do planejamento | #640, PR 2 |
