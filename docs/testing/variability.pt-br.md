# Variabilidade do baseline e sobreposição exaustiva

> [variability.md](variability.md). A versão em inglês é a fonte.

Este é o acompanhamento da [issue #644](https://github.com/A11yDevs/acessilia/issues/644),
registrado na #756. Ele substitui conclusões de execução única por uma medição
repetível e explicita o que a busca de pares de sobreposição prova — e o que não
prova.

- **Ferramenta:** [`scripts/tests/collect_timings.py`](../../scripts/tests/collect_timings.py)
  com `--repeat`.
- **Execução versionada:** [`variability.json`](variability.json) e
  [`variability.md`](variability.md).
- **Ambiente:** `develop` em `6b586fe9`, Python 3.12.13, quatro workers xdist,
  máquina de referência macOS sob carga normal de desktop.

## Método

```bash
uv run --extra dev python scripts/tests/collect_timings.py collect \
  --run --repeat 3 \
  --output var/timings/variability.json \
  --summary var/timings/variability.md

# Copy the machine-readable record and a generated summary when refreshing
cp var/timings/variability.json docs/testing/variability.json
cp var/timings/variability.md docs/testing/variability.md
```

Cada suíte roda três vezes na mesma invocação. O runner usa o mesmo ambiente
pytest sanitizado do harness de mutação: `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `PYTEST_CURRENT_TEST`, `PYTEST_DEBUG` e `PYTEST_DEBUG_TEMPROOT` do shell
são removidos. O registro da suíte mantém:

- as três execuções cruas (`runs`);
- a mediana de `junit_seconds`, `wall_seconds`, p50 e p95;
- `wall_seconds_min` e `wall_seconds_max`;
- `runs_count` e os totais de cobertura da última execução.

`compare` continua funcionando sobre as medianas. Uma execução única não é mais
apresentada como medição estável.

## Resultado de três execuções

| Suíte | Testes | Parede mediana (s) | Faixa (s) | JUnit mediano (s) |
|---|---:|---:|---:|---:|
| Aplicação | 3.303 | 254,45 | 249,25–369,78 | 240,99 |
| docstruct | 1.863 | 74,34 | 62,43–91,27 | 57,55 |
| SDK | 702 | 34,88 | 28,58–63,61 | 32,62 |
| core | 1.397 | 116,11 | 88,84–143,81 | 112,83 |
| **Total** | **7.265** | **479,78** | — | **444,00** |

As faixas são o ponto: a docstruct variou entre 62,4s e 91,3s e a aplicação
entre 249,3s e 369,8s na mesma sessão. Um atraso observado em uma execução não
deve ser atribuído a uma mudança de código sem medições repetidas e condições de
máquina comparáveis.

Esta tabela **não** é uma comparação antes/depois. Ela inclui testes e condições
de carga diferentes dos baselines anteriores; o efeito do cache da docstruct
continua sendo a observação estável (o teste mais lento fica em torno de 2–6s
conforme a carga — 6,174s no registro versionado — em vez de 23s, não o tempo
agregado da suíte).

## Subsunção de cobertura exaustiva vs. busca de pares

O relatório de sobreposição agora expõe os dois:

- `summary.coverage_subsets` / `coverage_subsets` — relações completas de
  subconjunto entre **assinaturas únicas**, independentes de Jaccard e do limite
  da busca de pares. As contagens do summary são exaustivas; o array JSON ainda
  é limitado por `--top`.
- `summary.pairs` / `pairs` — lista de pares ordenada por Jaccard. Uma linha
  coberta por mais de `max_element_tests` testes é removida da geração de
  candidatos, então pares que compartilham apenas essas linhas ficam de fora; a
  lista de pares é um **limite inferior**, não um censo completo. O relatório registra `pair_search_complete: false` e
  `pair_search_cap`.

Um par ausente em `pairs` não significa que não existe sobreposição; use
`coverage_subsets` para a relação completa de subconjuntos. As métricas de cada
par relatado continuam calculadas sobre os conjuntos completos.

## O que está coberto

- `collect_timings.py` tem `--repeat N`, e `combine_runs()` mantém mediana,
  mínimo/máximo e as execuções cruas.
- `run_suite` sem relatório JUnit tem teste com subprocesso simulado: retorna um
  registro de falha em vez de quebrar.
- `coverage_overlap` rotula a busca de pares como incompleta e nunca a apresenta
  como exaustiva.
- O baseline de três execuções está versionado para reprodução.

## Limitações

- A máquina de referência não é um host de benchmark isolado; a carga de
  desktop faz parte da faixa.
- Três execuções estimam dispersão, não um intervalo de confiança.
- A comparação é por suíte; o agregado é a soma das medianas.
- O limite de pares continua sendo um filtro de geração de candidatos. Ele é
  documentado e testável, não silenciosamente exaustivo.
