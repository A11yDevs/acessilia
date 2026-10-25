# Harness de benchmark

> English version: [English guide](bench.md)

`python -m scripts.bench` roda o core sobre um dataset de parsing de documentos,
pontua o resultado e compara execuções. É assim que a extração de estrutura do
core é medida no Dr.DocBench, e é assim que será medida no OmniDocBench e nos
próximos datasets.

## Onde fica cada parte

| Parte | Local | Específica do dataset? |
|---|---|---|
| Métricas (distância de edição de texto, ordem de leitura, TEDS, CDM, overall) | `docstruct.evaluation.metrics` | não |
| Pontuação de página (pareia tabelas e fórmulas pela ordem) | `docstruct.evaluation.markdown` | não |
| Aceite tune/holdout | `docstruct.evaluation.holdout` | não |
| Documento canônico → markdown de benchmark | `docstruct.export.markdown` | não |
| Payload da Toolbox → documento canônico | `scripts/bench/core.py` | não |
| Download, layout das páginas, formato de submissão | `scripts/bench/datasets/<nome>.py` | sim |

As métricas são aproximações locais para acompanhar a diferença entre
execuções. Para um número que vá ser reportado, rode o avaliador oficial do
benchmark sobre as predições.

## Fluxo

A Toolbox precisa estar acessível (valem as configurações `TOOLBOX_*` do core).

```bash
# 1. Materializa um split localmente: var/bench/<dataset>/<split>/data
uv run python -m scripts.bench download --dataset drdocbench --split dev --limit 100

# 2. Roda o core: var/bench/<dataset>/<split>/<run>/predictions/<item>.md (+ .blocks.json)
uv run python -m scripts.bench run --dataset drdocbench --split dev --run baseline

# 3. Pontua: report.json, pages.jsonl e drilldown.csv (piores páginas primeiro) no diretório da execução
uv run python -m scripts.bench score --dataset drdocbench --split dev --run baseline

# 4. Depois de uma mudança, roda e pontua de novo com outro nome e compara
uv run python -m scripts.bench compare var/bench/drdocbench/dev/baseline var/bench/drdocbench/dev/candidate

# 5. Empacota uma execução para o benchmark (Dr.DocBench: submission.zip do EvalAI)
uv run python -m scripts.bench submit --dataset drdocbench --split test --run baseline
```

`--root` aponta para uma árvore local existente em vez de `var/bench/.../data`;
`run` também aceita `--sample N`, `--item <id>`, `--provider` e `--save-raw`.
`run` substitui as predições anteriores da run e registra as páginas que cobriu
em `pages.txt`; `score` pontua só essas páginas, então uma run com `--sample`
não é pontuada contra o split inteiro. `score` sai com 1 quando nenhuma página
tem ground truth (o split `test`, por exemplo). Já `--resume` continua uma run
interrompida: as predições anteriores ficam e o `pages.txt` segue cobrindo todas
as páginas da seleção.

A pontuação calcula duas distâncias de Levenshtein por página. Sem o `rapidfuzz`
(instalado pelo extra `dev`), o docstruct usa Python puro, que leva cerca de
20 s para uma página de 3.000 caracteres.

`compare` aplica o critério de aceite de `docstruct.evaluation.holdout`: o split
é por documento (1/3 no holdout), e um candidato só é aceito se ganhar no tune,
não perder no holdout e nenhuma métrica cair além da tolerância. Sai com 1
quando o candidato é rejeitado, inclusive quando um dos subconjuntos não tem
páginas pontuáveis (amostra pequena demais) e quando uma métrica pontuada na
base não tem nenhum valor no candidato (por exemplo, ele parou de emitir
tabelas): sem isso a métrica sairia da média e contaria como ganho. Valores que
não podem ser calculados saem como `null`.

Uma métrica que some só em algumas páginas ainda deixa essas páginas fora da
sua média; no `drilldown.csv` esse componente fica em branco nessas páginas.

## Em um cluster Slurm

`scripts/bench/slurm/` tem três jobs; cada um carrega o `env.sh`, que exige `WS`
(o workspace com `repos/acessilia`, `repos/acessilia-toolbox` e `data/`) e mantém
todos os caches e execuções dentro dele (`BENCH_VAR=$WS/bench`). Submeta a partir
de `$WS` e passe a partição com `-p`.

| Job | O quê |
|---|---|
| `setup.sbatch` | venvs e modelos da Toolbox, do docling-serve e do MinerU, venv deste repositório; opcionalmente um snapshot de dataset do HuggingFace (`HF_DATASET`, `HF_PATTERN`, `DATASET_DIR`) |
| `bench.sbatch` | sobe o provider (`PROVIDER=docling\|mineru`) e a Toolbox dentro do job, em portas derivadas do id do job, e roda `scripts.bench run --resume` e `score`; submeter de novo o mesmo `RUN` retoma de onde parou |
| `eval_official.sbatch` | monta a árvore de janelas de uma página do avaliador oficial para cada execução em `RUNS` e pontua com `$WS/repos/DrDocBench` (`CONFIG` é a configuração do avaliador; `cdm_env.sh` para o CDM) |

```bash
cd $WS
sbatch -p <partition> -c 8 --mem 32G --time 04:00:00 --job-name mineru-dev \
  --export=ALL,WS=$PWD,DATASET=drdocbench,ROOT=$PWD/data/drdocbench/dev,RUN=mineru,PROVIDER=mineru \
  repos/acessilia/scripts/bench/slurm/bench.sbatch
```

## Acrescentando um dataset

Escreva `scripts/bench/datasets/<nome>.py` com uma classe que implemente
`scripts.bench.datasets.base.Dataset` e registre-a em
`scripts/bench/datasets/__init__.py`:

- `download(split, root, limit)` grava o split em `root`;
- `pages(root)` devolve um `BenchPage` por página (imagem, caminho do markdown
  de ground truth, metadados de que a submissão precisa);
- `build_submission(pages, predictions, out)` empacota uma execução.

Predições e pontuação são compartilhadas: quando o ground truth do dataset não
for markdown, converta-o para markdown no `download`, para que o `score` se
aplique sem mudanças.

## Caso de referência de matemática

`python -m scripts.bench.math_case` pontua um documento inteiro em vez de um
dataset de páginas: `velocidade-instantanea.pdf` (id `036` no
[acessilia-dataset](https://github.com/A11yDevs/acessilia-dataset), em
`input/math-reference/`), uma apostila de cálculo de cinco páginas em pdfTeX,
com matemática inline e display, uma equação numerada e matemática nos
cabeçalhos de tabela. O ground truth lista o LaTeX esperado de cada fórmula
(`ground_truth.csv`) e as verificações de texto, estrutura e fala que as
fórmulas não cobrem (`expectations.json`).

```bash
# Processa o PDF no core e pontua (precisa do Toolbox e do provedor de modelo)
uv run python -m scripts.bench.math_case run --out var/bench/math-reference/<run>

# Pontua saídas que você já tem: o JSON do documento canônico e o TXT,
# opcionalmente o PDF/UA (precisa do pdftotext)
uv run python -m scripts.bench.math_case score --canonical doc.json --txt doc.txt --pdf-ua doc.pdf_ua.pdf
```

O clone do dataset é lido de `tests/dataset` ou de `ACESSILIA_TEST_DATASET_DIR`.
O placar (`scorecard.md`, `scorecard.json`) informa:

- fórmulas display, pareadas com o ground truth da mesma página: CDM, o recall
  dos tokens estruturais (`\frac`, `^`, `_`, `\lim`, `\mathbb`...), MathML, forma
  falada e de onde veio o LaTeX (`extractor`, `math.recognize`, `vision`). O
  recall estrutural é o número a acompanhar: uma fórmula achatada a partir da
  camada de texto do PDF mantém as letras, então sua CDM de saco de tokens
  continua alta, mas perde todos os tokens estruturais;
- expressões inline e cabeçalhos/células de tabela entregues como matemática;
- as verificações de texto, estrutura e fala, com cada falha listada.

Com `--pdf-ua` (e sempre no `run`), as verificações de texto rodam nas duas
saídas e entra a verificação de títulos auto-numerados; por isso o placar
começa pelas saídas que pontuou: compare dois placares só quando essa linha
for igual.

Uma PR que muda como matemática, reparo de texto ou estrutura chegam às saídas
cola o placar antes e depois na descrição. `tests/test_math_case_e2e.py`
(`-m e2e`) roda o caso e trava o que já passa.

## Snapshot dos experimentos do Dr.DocBench

O código dos experimentos da shared task (variantes de fusão, jobs Slurm,
replay congelado) está preservado na tag `drbench-2026-snapshot`: o que cada
script fazia e para onde foi seu algoritmo está em
[CODE.pt-br.md](drbench/experiments/CODE.pt-br.md), e como rodá-lo no
[runbook](drbench/experiments/RUNBOOK.pt-br.md).
