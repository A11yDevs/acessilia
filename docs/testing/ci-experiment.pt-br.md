# Experimento de CI: baseline, paralelo e seleção em observação

> [ci-experiment.md](ci-experiment.md). A versão em inglês é a fonte.

Este é o primeiro registro de observação da [issue #767](https://github.com/A11yDevs/acessilia/issues/767),
o experimento exigido pela proposta de CI da [#644](https://github.com/A11yDevs/acessilia/issues/644).
A suíte completa continua sendo o gate; este documento compara modos de execução
antes de considerar qualquer gate seletivo.

## Modos

| Modo | Configuração |
|---|---|
| A — baseline | um único job `tests (Python 3.12)` executa as suítes da aplicação, docstruct, SDK e core em sequência |
| B — paralelo | `quality` e quatro pernas `component-tests` rodam em paralelo; `tests (Python 3.12)` é um agregador que falha fechado |
| C — seletivo | recomendação do `detect-changes` em modo observação; não é gate |

## Amostra

Duas execuções bem-sucedidas de pull request do mesmo workflow, antes e depois
da mudança paralela. Não são o mesmo código, então a comparação é indicativa,
não um benchmark controlado.

| Modo | Execução | Tempo de parede | Job `tests` | Job-minutes |
|---|---|---:|---:|---:|
| A | [45174924436](https://github.com/A11yDevs/acessilia/actions/runs/45174924436) | 3m07s | 3,05m | 7,43 |
| B | [45193011145](https://github.com/A11yDevs/acessilia/actions/runs/45193011145) | 2m21s | 0,20m (agregador) | 8,45 |

Os job-minutes incluem os jobs de isolamento e segurança; medem o consumo
agregado de runner, não apenas as suítes.

## Primeiras observações

- O caminho crítico dos testes caiu de **3,05m para 1,22m** (perna
  `app tests`); o agregador acrescenta **0,20m**. O check `tests (Python 3.12)`
  deixou de ser o job de teste mais lento.
- O tempo de parede de ponta a ponta caiu de **3m07s para 2m21s** neste par.
- O total de job-minutes subiu de **7,43 para 8,45** porque cinco jobs provedores
  repetem checkout/install. O paralelismo reduziu latência, não consumo.
- O **scan da imagem de container (2,28m)** passou a ser o caminho crítico no
  modo B. Um ganho adicional exige atacar esse job, não apenas as suítes.
- A seleção em observação rodou com sucesso no modo B. Para o PR #763, os
  caminhos alterados de workflow/scripts selecionaram corretamente todas as
  suítes; nenhum falso negativo foi observável porque o modo C não pula nada.

## Decisão

Nenhum gate seletivo foi adotado. A suíte completa continua obrigatória
enquanto os artefatos de observação se acumulam. A decisão de gate precisa de um
conjunto representativo de PRs, falsos negativos observados e execuções repetidas
que separem a mudança de código da carga da máquina.

## Limitações

- Uma execução por modo, com conteúdo de PR diferente; o delta de parede não é
  uma medição controlada.
- Os job-minutes derivam dos horários de início/fim do GitHub e incluem
  download/setup.
- Falsos negativos da seleção só podem ser medidos quando a recomendação for
  comparada com PRs que tiveram falhas conhecidas.
- O experimento deve ser repetido quando os jobs de segurança/imagem mudarem; o
  caminho crítico pode voltar para os testes.

Parte de #767 e #644.
