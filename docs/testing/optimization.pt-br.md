# Otimização da suíte de testes: baseline e método

> [optimization.md](optimization.md). A versão em inglês é a fonte.

Este é o PR 1 da [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
instrumentação e baseline reproduzível das quatro suítes de teste. Nenhum teste
ou código de produção muda. O baseline é a referência para a análise de
sobreposição (PR 2), o experimento de mutation testing/subsunção (PR 3) e as
otimizações (PR 4).

- **Snapshot:** `develop` em `cd7003d2` (2026-11-23), Python 3.12.13.
- **Ferramenta:** [`scripts/tests/collect_timings.py`](../../scripts/tests/collect_timings.py),
  biblioteca padrão mais os pacotes que o projeto já instala.
- **Baseline legível por máquina:** [`baseline.json`](baseline.json).
- **Baseline serial da aplicação:** [`baseline-serial-app.json`](baseline-serial-app.json).
- **Escopo:** aplicação (`tests/`), docstruct (`libs/docstruct/tests`), SDK
  (`libs/sdk/tests`) e core (`libs/core/tests`).

## Método

`collect_timings.py collect --run` executa cada suíte no ambiente raiz, com a
mesma configuração de cobertura usada pelo gate de CI, e registra:

| Medida | Origem |
|---|---|
| Número de testes, falhas, erros, pulos | atributos do `testsuite` JUnit |
| Duração por teste, p50/p95, testes mais lentos | `testcase@time` do JUnit |
| Tempo JUnit da suíte | soma de `testsuite@time` |
| Tempo de parede da suíte | `time.monotonic()` em volta do processo pytest |
| Cobertura de desvios | `coverage.json` do pytest-cov (linhas e desvios) |
| Ambiente | revisão, Python, plataforma, versões de pytest, xdist e Coverage |

Um segundo modo lê relatórios produzidos pelo CI, então o baseline pode ser
atualizado sem repetir as suítes:

```bash
uv run --extra dev python scripts/tests/collect_timings.py collect \
  --report app=test-results.xml \
  --report docstruct=libs/docstruct/docstruct-test-results.xml \
  --report sdk=libs/sdk/sdk-test-results.xml \
  --report core=libs/core/core-test-results.xml \
  --coverage-dir var/coverage \
  --output var/timings/baseline.json
```

O job `tests` do CI escreve o mesmo resumo no sumário do job e publica o
artefato `timing-baseline-py*`. Ele é apenas informativo: `continue-on-error`
impede que um relatório ausente altere o gate.

### Como reproduzir

```bash
# As quatro suítes, aplicação com quatro workers
make test-baseline

# Comparar uma nova execução com o baseline versionado
make test-baseline-compare BASELINE=var/timings/baseline.json

# A suíte da aplicação em modo serial, para a comparação de paralelismo
uv run --extra dev python scripts/tests/collect_timings.py collect --run --only app \
  --xdist 0 --work-dir var/timings-serial \
  --output var/timings-serial/baseline.json
```

Os números versionados vêm de uma execução em máquina de referência macOS
(12 núcleos lógicos, 16 GB de RAM). São indicadores, não limites rígidos:
execute o mesmo comando na mesma máquina antes de tratar uma diferença como
regressão.

## Baseline

### Por componente

| Suíte | Testes | JUnit (s) | Parede (s) | p50 (s) | p95 (s) | Cobertura (desvios) |
|---|---:|---:|---:|---:|---:|---:|
| Aplicação (`tests/`) | 3.181 | 151,76 | 157,23 | 0,014 | 0,216 | 87,9% |
| docstruct | 1.859 | 93,09 | 96,48 | 0,006 | 0,076 | 87,0% |
| SDK | 702 | 28,34 | 31,20 | 0,027 | 0,072 | 97,3% |
| core | 1.379 | 37,13 | 41,25 | 0,003 | 0,122 | 82,7% |
| **Total** | **7.121** | **310,32** | **326,17** | — | — | — |

A suíte da aplicação representa 49% do tempo JUnit; a docstruct representa 30%,
mesmo sendo uma biblioteca pura. As quatro suítes executam em sequência e cada
uma importa o projeto novamente, então o tempo de parede total é um pouco maior
que a soma dos tempos JUnit.

### Paralelismo

A suíte da aplicação é a única que o projeto paraleliza. Mesma revisão, mesmas
opções de cobertura, uma execução serial e outra com quatro workers:

| Execução | Testes | JUnit (s) | Parede (s) | Teste mais lento (s) |
|---|---:|---:|---:|---:|
| serial | 3.181 | 884,30 | 890,15 | 88,56 |
| `-n 4 --dist worksteal` | 3.181 | 151,76 | 157,23 | 52,19 |

A execução com quatro workers é **5,7× mais rápida em tempo de parede** nesta
máquina. O teste mais lento é um caso longo do juiz VLM que não pode ser
dividido, então ele sozinho impõe um piso de cerca de 52 segundos ao job da
aplicação. `--dist worksteal` importa: a distribuição entrega o próximo teste
ao worker livre em vez de esperar um lote fixo de módulos.

As bibliotecas continuam seriais: docstruct leva 96 segundos, o SDK 31 e o core
41, todos abaixo do custo de iniciar quatro workers e repetir suas fixtures.
É a mesma escolha que o Makefile e o CI já fazem.

### Gargalos

| Suíte | Teste | Segundos | Fração do tempo de parede |
|---|---|---:|---:|
| Aplicação | `TestVlmPairwiseJudge::test_long_page_is_flagged_as_truncated` | 52,19 | 33% |
| Aplicação | `test_it_counts_test_functions` | 8,18 | 5% |
| Aplicação | `test_every_exception_is_still_needed` | 8,14 | 5% |
| docstruct | `test_long_parent_chains_are_acyclic` | 23,59 | 24% |
| docstruct | `test_imports_outside_the_standard_library_are_guarded_accelerators` | 4,25 | 4% |
| core | varreduras estáticas de `test_boundary.py` (14 testes) | 8,72 | 21% |

Dois padrões dominam a cauda:

1. **Casos deliberadamente caros.** O juiz VLM e a cadeia de 2.000 elementos
   exercitam escala real. São candidatos a revisão baseada em evidências, não
   a remoção automática.
2. **Varreduras estáticas do repositório.** Os guardas de arquitetura, pureza e
   português percorrem a árvore rastreada em vários testes. São baratos
   individualmente, mas somam, e não podem ser trocados por uma verificação
   unitária mais estreita sem perder o guarda.

A lista por teste está em [`baseline.json`](baseline.json). Os próximos PRs a
usam para priorizar: sobreposição sem duração é só metade da questão de custo.

## Limitações

- **Uma execução por suíte.** O tempo JUnit varia com a carga da máquina; o
  teste mais lento levou 88,56s na execução serial contra 52,19s na paralela. A
  execução serial é um único processo com um conjunto residente muito maior e
  sem isolamento entre workers, então GC e pressão de memória são causas
  plausíveis; esta medição não estabelece qual delas. Compare execuções feitas
  nas mesmas condições, de preferência mais de uma vez.
- **O tempo de coleta não está no JUnit.** O pytest reporta as durações de
  chamada, setup e teardown, não a coleta. O tempo de parede a inclui.
- **A atribuição a fixtures é indireta.** Um setup lento aparece no tempo do
  `testcase`, mas o JUnit não diz qual fixture o causou. O PR 2 combina
  durações com sobreposição de cobertura para encontrar trabalho repetido.
- **A cobertura é por suíte, não por teste.** Os contextos por teste usados
  pelo PR 2 vêm de uma execução separada com `--cov-context=test`; eles não
  fazem parte deste baseline.

## O que este baseline não decide

Nenhum teste é removido, consolidado ou marcado por este PR. Um teste com alta
sobreposição de cobertura ainda pode ser o único que verifica um contrato, e um
teste lento pode ser o único que exercita escala real. O baseline registra o
custo; o PR 2 e o PR 3 registram a evidência antes de o PR 4 mudar qualquer
coisa.
