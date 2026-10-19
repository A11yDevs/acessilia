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

`compare` aplica o critério de aceite de `docstruct.evaluation.holdout`: o split
é por documento (1/3 no holdout), e um candidato só é aceito se ganhar no tune,
não perder no holdout e nenhuma métrica cair além da tolerância. Sai com 1
quando o candidato é rejeitado, inclusive quando um dos subconjuntos não tem
páginas pontuáveis (amostra pequena demais).

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

## Snapshot dos experimentos do Dr.DocBench

O código dos experimentos da shared task (variantes de fusão, jobs Slurm,
replay congelado) está preservado na tag `drbench-2026-snapshot`: o que cada
script fazia e para onde foi seu algoritmo está em
[CODE.pt-br.md](drbench/experiments/CODE.pt-br.md), e como rodá-lo no
[runbook](drbench/experiments/RUNBOOK.pt-br.md).
