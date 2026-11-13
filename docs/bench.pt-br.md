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

A Toolbox precisa estar acessível. O harness configura os próprios clientes do
SDK (`scripts/bench/toolbox.py`), a partir do ambiente ou do `.env`, com os
mesmos nomes de variáveis e padrões do core: `TOOLBOX_BASE_URLS` (ou então
`TOOLBOX_BASE_URL`), `TOOLBOX_API_KEY`, `TOOLBOX_TIMEOUT_SECONDS`,
`TOOLBOX_RETRIES`, `TOOLBOX_RETRY_BACKOFF_SECONDS` e `TOOLBOX_PROVIDER`.

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

Com `--pdf-ua` (e no `run`, a não ser com `--no-pdf-ua`), as verificações de texto rodam nas duas
saídas e entra a verificação de títulos auto-numerados; por isso o placar
começa pelas saídas que pontuou: compare dois placares só quando essa linha
for igual.

Uma PR que muda como matemática, reparo de texto ou estrutura chegam às saídas
cola o placar antes e depois na descrição. `tests/test_math_case_e2e.py`
(`-m e2e`) roda o caso e trava o que já passa.

### Paridade de uma mudança que não deve alterar a saída

O `compare` confere duas saídas do caso campo a campo, para uma refatoração
que precisa deixá-las como estavam (a paridade da cadeia de fórmula da
ADR-0017):

```bash
uv run python -m scripts.bench.math_case compare base/canonical.json candidate/canonical.json --out var/bench/math-reference/<comparacao>
```

Ele compara, de cada fórmula, o LaTeX, o MathML, a forma falada, o método de
reconhecimento, a concordância com a camada de texto, a camada de texto e o
número da equação; de cada bloco, tabelas incluídas, o texto e as expressões
inline; de cada tabela, a forma e as células; a estrutura dos blocos; e os
avisos técnicos. Sai com 1 quando há diferença.

O que um modelo de visão escreveu pode diferir entre duas execuções
quaisquer, então aparece à parte e não reprova a comparação:
- o LaTeX de uma fórmula que ele leu, e o que o core deriva desse LaTeX
  (MathML, forma falada, concordância, número da equação) só quando o próprio
  LaTeX difere;
- a descrição de uma imagem que a etapa de imagens marca como do modelo
  (`vision_description_complete`, `vision_confidence`);
- uma tabela que o agente de dados releu pela imagem (`table_review`).

Todo o resto conta, mesmo quando a resposta de um modelo de visão o causou: o
método de reconhecimento, um texto alternativo de fallback, a estrutura dos
blocos (uma fórmula que o modelo tomou por imagem) e os avisos técnicos.
Inspecione esses casos. Rode a base duas vezes para ver quanto varia sozinho.

O core e a Toolbox guardam resultados pelo hash da fonte, não pelo código que
os produziu, então cada execução precisa de uma fonte que nenhuma execução
viu: acrescente um comentário depois do `%%EOF` (um leitor de PDF o ignora). O
caso fica no branch `main` do acessilia-dataset (`input/math-reference/`);
aponte o `ACESSILIA_TEST_DATASET_DIR` para um checkout dele, porque um worktree
deste repositório não tem `tests/dataset`.

```bash
export ACESSILIA_TEST_DATASET_DIR=/caminho/do/acessilia-dataset   # no branch main
for run in base candidate; do
  cp "$ACESSILIA_TEST_DATASET_DIR/input/math-reference/velocidade-instantanea.pdf" "/tmp/036-$run.pdf"
  printf '%% %s %s\n' "$run" "$(date +%s)" >> "/tmp/036-$run.pdf"
done
# Num checkout de cada commit (git worktree add ../base <commit>):
uv run python -m scripts.bench.math_case run --pdf /tmp/036-base.pdf --out var/bench/math-reference/base
```

## Snapshot dos experimentos do Dr.DocBench

O código dos experimentos da shared task (variantes de fusão, jobs Slurm,
replay congelado) está preservado na tag `drbench-2026-snapshot`: o que cada
script fazia e para onde foi seu algoritmo está em
[CODE.pt-br.md](drbench/experiments/CODE.pt-br.md), e como rodá-lo no
[runbook](drbench/experiments/RUNBOOK.pt-br.md).
