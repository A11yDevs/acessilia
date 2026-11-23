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
  --output docs/testing/variability.json \
  --summary docs/testing/variability.md
```

Cada suíte roda três vezes na mesma invocação. O registro da suíte mantém:

- as três execuções cruas (`runs`);
- a mediana de `junit_seconds`, `wall_seconds`, p50 e p95;
- `wall_seconds_min` e `wall_seconds_max`;
- `runs_count` e os totais de cobertura da última execução.

`compare` continua funcionando sobre as medianas. Uma execução única não é mais
apresentada como medição estável.

## Resultado de três execuções

| Suíte | Testes | Parede mediana (s) | Faixa (s) | JUnit mediano (s) |
|---|---:|---:|---:|---:|
| Aplicação | 3.298 | 247,39 | 193,14–247,74 | 234,83 |
| docstruct | 1.863 | 47,54 | 30,79–48,78 | 37,80 |
| SDK | 702 | 41,88 | 31,91–44,11 | 40,10 |
| core | 1.397 | 59,50 | 53,74–60,02 | 57,67 |
| **Total** | **7.260** | **396,31** | — | **370,39** |

As faixas são o ponto: a docstruct variou entre 30,8s e 48,8s e a aplicação
entre 193,1s e 247,7s na mesma sessão. Um atraso observado em uma execução não
deve ser atribuído a uma mudança de código sem medições repetidas e condições de
máquina comparáveis.

Esta tabela **não** é uma comparação antes/depois. Ela inclui testes e condições
de carga diferentes dos baselines anteriores; o efeito do cache da docstruct
continua sendo a observação estável (o teste mais lento fica em torno de 2–3s
em vez de 23s, não o tempo agregado da suíte).

## Subsunção de cobertura exaustiva vs. busca de pares

O relatório de sobreposição agora expõe os dois:

- `summary.coverage_subsets` / `coverage_subsets` — relações completas de
  subconjunto entre **assinaturas únicas**, independentes de Jaccard e do limite
  de apresentação. Esta é a visão exaustiva de subsunção.
- `summary.pairs` / `pairs` — lista de pares ordenada por Jaccard. Uma linha
  coberta por mais de `max_element_tests` testes é usada apenas para propor
  candidatos, então a lista de pares é um **limite inferior**, não um censo
  completo. O relatório registra `pair_search_complete: false` e
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
