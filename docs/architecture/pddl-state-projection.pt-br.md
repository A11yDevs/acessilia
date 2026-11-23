# A projeção do estado observado em PDDL (#640, PR 1)

Inglês, versão normativa: [English version](pddl-state-projection.md)

A [ADR-0029](../adr/0029-symbolic-core-every-step-planned.pt-br.md) compila
cada problema de planejamento a partir do estado observado: os fatos do
manifesto, as obrigações, os resultados já registrados e um snapshot do
catálogo. Esta página documenta o que `PddlProblemCompiler.compile`
(`planning/pddl_processor.py`) projeta hoje, para o domínio v2.3, e o que
ainda falta. `libs/core/tests/test_pddl_state_projection.py` tem um teste por
regra, então uma mudança na projeção aparece no diff.

## Entradas

`compile(manifest, *, selected_roots=None, unavailable_methods=())`. O
orquestrador o chama pelo `PlanningEngine` (#744), com um `PlanningProblem`:

- `manifest`: o manifesto de processamento, como observado até agora;
- `selected_roots`: as obrigações a planejar, ou `None` (veja abaixo);
- `unavailable_methods`: os métodos que o plano não pode usar. São os
  métodos sem handler registrado e, quando o gate de disponibilidade está em
  modo `enforce`, os métodos cuja capacidade ou provider da Toolbox falta no
  snapshot do catálogo.

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
| Um método fora de `unavailable_methods` | `(available m)` | Por método, não por capacidade ou provider |
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
- **Métodos.** Uma obrigação pendente sem método admissível, disponível e
  não tentado.
- **Catálogo v2.3.** Para um kind do catálogo v2.3, métodos admissíveis fora
  dele, ou um método sem custo.
- **Métodos indisponíveis desconhecidos.** Um método indisponível que o
  manifesto não declara: um erro de digitação, não uma lacuna de capacidade.
- **Ainda não: ciclos e dependências desconhecidas.** O modelo do manifesto
  os recusa, mas um introduzido por replanejamento compila: o planejador
  interno recusa um ciclo ao ordenar, o Fast Downward não encontra plano, e
  uma dependência desconhecida levanta um `KeyError` cru. O compilador
  deveria recusar os dois
  ([#783](https://github.com/A11yDevs/acessilia/issues/783)).
- **O problema renderizado.** O `PddlProblemValidator` o confere contra a
  projeção.

## Identidade

- `CompiledProblem.sha256` é o hash do texto do problema. Ele muda
  exatamente quando o estado projetado muda, e o plano o registra
  (`problem_sha256`). O coordenador o confere desde o #744.
- `manifest_sha256` é o hash do manifesto inteiro, inclusive do que não é
  projetado.
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
| A disponibilidade de capacidades e providers é predicado do problema | O gate a transforma em `unavailable_methods`, fora do problema, e só no modo `enforce` | PR 1, segunda parte: o snapshot do catálogo como fatos (requisitos por método, capacidades e providers oferecidos) e a disponibilidade derivada no domínio. Isso exige uma nova versão do domínio |
| O `toolbox_gate` vira só relatório | Ele decide `unavailable_methods` | #640, PR 2, depois dos predicados |
| Ações operacionais ligadas a um id de capacidade e versão exata | Os métodos nomeiam handlers locais | #640, PR 2, com os fragmentos de domínio |
| Um resultado atualiza o estado uma vez por `operation_id` | Os status e as tentativas do manifesto | #640, PR 3, com o journal da ADR-0020 |
| Inspeção, extração e enriquecimento são ações | Rodam antes do planejamento | #640, PR 2 |
