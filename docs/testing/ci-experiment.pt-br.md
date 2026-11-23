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
| B2 — #787 após setup compartilhado | [45251360702](https://github.com/A11yDevs/acessilia/actions/runs/45251360702) | 2m11s | 0,20m (agregador) | 8,37 |

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
- Após a action de setup compartilhado e o cache funcional do setup-uv (#788), a
  execução B2 ficou em **2m11s / 8,37 job-minutes** (perna app 1,87m, scan da
  imagem 1,80m). A mudança de manutenção não reduziu o total de runner-minutes;
  o scan da imagem continua sendo o caminho crítico.
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

### Dimensão de integração e mudanças só de CI

Os PRs de acompanhamento na janela da amostra shadow (#788–#808) exercitaram a
dimensão `app integration` e mudanças majoritariamente em CI/segurança.
Reaplicando o seletor atual sobre as listas de arquivos:

| PR | Área alterada | Selecionadas | `integration_required` | Conservadora |
|---|---|---|---|---|
| #788 | action de setup compartilhada, workflows, tests | todas | sim | não |
| #793 | workflow de CI, docs, `pyproject.toml`, tests | todas | sim | não |
| #795 | workflow de segurança, docs, tests | todas | não | não |
| #800 | workflow de release, `SECURITY.md`, tests | todas | não | não |
| #802 | workflow de CI, seletor, docs, tests | todas | sim | não |
| #807 | workflows CodeQL/segurança, tests | todas | não | não |
| #808 | seletor, docs, tests | todas | não | não |

`.github/**` e `scripts/**` são transversais, então mudanças só de CI ainda
selecionam todas as suítes. A flag de integração segue a lista focada: apenas
os PRs que tocaram `.github/workflows/ci.yml` ou seu suporte de integração a
selecionaram.

### Replay de falhas históricas

Para testar a direção de risco — uma falha que a suíte completa pega mas o
conjunto selecionado pularia — o seletor atual foi reaplicado a pull requests
com falhas conhecidas:

| PR | Execução | Job / passo com falha | Resultado do seletor | Falso negativo? |
|---|---|---|---|---|
| #732 | [45001010971](https://github.com/A11yDevs/acessilia/actions/runs/45001010971) | `tests (Python 3.12)` / passo Ruff (quality rodava dentro de tests na época) | todas | não |
| #726 | [44994569632](https://github.com/A11yDevs/acessilia/actions/runs/44994569632) | testes do core | todas | não |
| #713 | [44977779847](https://github.com/A11yDevs/acessilia/actions/runs/44977779847) | testes da aplicação | todas | não |
| #711 | [44976566900](https://github.com/A11yDevs/acessilia/actions/runs/44976566900) | testes da aplicação | sdk, core, app | não |
| #709 | [44972669665](https://github.com/A11yDevs/acessilia/actions/runs/44972669665) | testes da aplicação | todas | não |
| #621 | [44683419408](https://github.com/A11yDevs/acessilia/actions/runs/44683419408) | testes da aplicação | todas (conservadora) | não |
| #781 | [45254071576](https://github.com/A11yDevs/acessilia/actions/runs/45254071576) | testes do core (mais isolado/agregador) | todas (artefato shadow) | não |

O conjunto selecionado continha a suíte que falhou em todas as execuções
reaplicadas, então esta amostra produziu **zero falsos negativos**. Os replays
usam o seletor atual sobre a lista de arquivos de cada PR; apenas o #781 tem
artefato da execução original, e ele usa o schema v1. Isso é evidência, não uma
prova de completude.

## Decisão

Nenhum gate seletivo foi adotado. A suíte completa continua obrigatória. O
replay de falhas adiciona regressões reais à observação, mas a amostra ainda é
pequena, a maioria dos replays é retrospectiva e nenhuma execução controlada
repetida separa a mudança de código da carga da máquina. A duplicação de setup
dos provedores e o caminho crítico do scan da imagem estão na
[#778](https://github.com/A11yDevs/acessilia/issues/778). A decisão de gate
ainda precisa de um conjunto representativo maior e de uma comparação
controlada.

## Limitações

- Uma execução por modo, com conteúdo de PR diferente; o delta de parede não é
  uma medição controlada.
- Os job-minutes derivam dos horários de início/fim do GitHub e incluem
  download/setup.
- A maioria dos replays de falha usa o seletor atual sobre uma lista de
  arquivos histórica, não o artefato shadow produzido na época; o #781 é a
  exceção. O replay não detecta um caminho ausente do diff nem uma falha
  causada por ambiente não representado na lista de arquivos.
- O experimento deve ser repetido quando os jobs de segurança/imagem mudarem; o
  caminho crítico pode voltar para os testes.
- Em pull requests o scan da imagem agora é condicional a entradas da imagem
  (`infra/**`, `pyproject.toml`, `uv.lock`, manifestos e locks das bibliotecas,
  `.dockerignore`, `.python-version`, `.trivyignore`, workflow de segurança);
  pushes, `workflow_dispatch` e o schedule semanal continuam escaneando
  incondicionalmente. A auditoria de dependências permanece incondicional.
- `docs/testing.pt-br.md` ainda registra os valores da era #448 (1m59s /
  59s–1m26s). O job absorveu Ruff/Mypy em 2026-11-20 e a suíte cresceu; os
  números aqui são a amostra comparável de 2026-11-23, não uma contradição do
  registro histórico.

Parte de #767 e #644.
