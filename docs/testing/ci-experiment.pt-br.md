# Experimento de CI: baseline, paralelo e seleção em observação

> [ci-experiment.md](ci-experiment.md). A versão em inglês é a fonte.

Este é o primeiro registro de observação da [issue #767](https://github.com/A11yDevs/acessilia/issues/767),
o experimento exigido pela proposta de CI da [#644](https://github.com/A11yDevs/acessilia/issues/644).
A suíte completa continua sendo o gate; este documento compara modos de execução
antes de considerar qualquer gate seletivo.

## Modos

| Modo | Configuração |
|---|---|
| A — baseline | um único job `tests (Python 3.12)` executa as suítes da aplicação, docstruct, SDK e core em sequência, mais os passos de Ruff/Mypy/contrato |
| B — paralelo | `quality` e quatro pernas `component-tests` rodam em paralelo; `tests (Python 3.12)` é um agregador que falha fechado |
| C — seletivo | recomendação do `detect-changes` em modo observação; não é gate |

## Amostra

Duas execuções bem-sucedidas de pull request do mesmo workflow, antes e depois
da mudança paralela. Não são o mesmo código, então a comparação é indicativa,
não um benchmark controlado.

| Modo | Execução | Tempo de parede | Job `tests` | Job-minutes |
|---|---|---:|---:|---:|
| A — branch #748 | [45174924436](https://github.com/A11yDevs/acessilia/actions/runs/45174924436) | 3m07s | 3,05m | 7,47 |
| B — #771 | [45193011145](https://github.com/A11yDevs/acessilia/actions/runs/45193011145) | 2m21s | 0,20m (agregador) | 8,47 |

Os job-minutes incluem os jobs de isolamento e segurança; jobs pulados são
excluídos porque não consomem runner. Os valores medem o consumo agregado, não
apenas as suítes.

## Primeiras observações

- O job `tests` caiu de **3,05m para 1,22m** (perna `app tests`); a cadeia
  completa de testes (início das pernas até o fim do agregador) leva cerca de
  **1,47m**, não 1,22 + 0,20. O check `tests (Python 3.12)` deixou de ser o job
  de teste mais lento.
- O modo A também rodava Ruff/Mypy/Mypy 3.11 (~39s) dentro do job; agora isso
  fica em `quality`. A parte puramente de suítes era ~131s sequencial em A
  contra a perna mais longa de 73s em B.
- O tempo de parede de ponta a ponta caiu de **3m07s para 2m21s** neste par.
- O total de job-minutes subiu de **7,47 para 8,47** porque cinco jobs provedores
  repetem checkout/install. O paralelismo reduziu latência, não consumo.
- O **scan da imagem de container (2,28m)** passou a ser o caminho crítico no
  modo B. Um ganho adicional exige atacar esse job, não apenas as suítes.
- A seleção em observação rodou com sucesso no modo B (PR #771). Seus caminhos
  alterados em `scripts/tests/**` selecionaram todas as suítes porque
  `scripts/**` é transversal; a execução do PR #763 fez o mesmo para
  `.github/**` e `scripts/**`. Nenhum falso negativo foi observável porque o
  modo C não pula nada.

## Seleções em observação

O artefato `test-selection-shadow` é produzido para todo PR de acompanhamento.
Estes cinco PRs mesclados ilustram cada regra; as cinco execuções de CI
passaram, então isso não prova que o seletor teria capturado uma regressão (o
modo C não é usado para pular nada).

| PR | Área alterada | Selecionadas | Não selecionadas | Conservadora |
|---|---|---|---|---|
| #766 | core | core, app | docstruct, SDK | não |
| #769 | somente `tests/**` | app | docstruct, SDK, core | não |
| #771 | `scripts/**`, docs, tests | todas | — | não |
| #772 | docs | app | docstruct, SDK, core | não |
| #776 | docstruct | todas | — | não |

Isso corresponde às regras documentadas: `tests/**` e docs mantêm a suíte da
aplicação, uma mudança no core seleciona core+app, docstruct seleciona todos os
consumidores e `scripts/**` é transversal. A amostra ainda contém apenas PRs
verdes.

## Decisão

Nenhum gate seletivo foi adotado. A suíte completa continua obrigatória
enquanto os artefatos de observação se acumulam. A duplicação de setup dos
provedores e o caminho crítico do scan da imagem estão na
[#778](https://github.com/A11yDevs/acessilia/issues/778). A decisão de gate
precisa de um conjunto representativo de PRs, falsos negativos observados e
execuções repetidas que separem a mudança de código da carga da máquina.

## Limitações

- Uma execução por modo, com conteúdo de PR diferente; o delta de parede não é
  uma medição controlada.
- Os job-minutes derivam dos horários de início/fim do GitHub e incluem
  download/setup.
- Falsos negativos da seleção só podem ser medidos quando a recomendação for
  comparada com PRs que tiveram falhas conhecidas.
- O experimento deve ser repetido quando os jobs de segurança/imagem mudarem; o
  caminho crítico pode voltar para os testes.
- Em pull requests o scan da imagem agora é condicional a entradas da imagem
  (`infra/**`, `pyproject.toml`, `uv.lock`, locks das bibliotecas, `.trivyignore`,
  workflow de segurança); pushes para branches de integração e o schedule semanal
  continuam escaneando incondicionalmente. A auditoria de dependências permanece
  incondicional.
- `docs/testing.pt-br.md` ainda registra os valores da era #448 (1m59s /
  59s–1m26s). O job absorveu Ruff/Mypy em 2026-11-20 e a suíte cresceu; os
  números aqui são a amostra comparável de 2026-11-23, não uma contradição do
  registro histórico.

Parte de #767 e #644.
