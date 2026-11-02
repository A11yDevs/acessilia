# Dr.DocBench — Benchmark de extração de estrutura

Dr.DocBench é a shared task de referência usada para avaliar provedores de
extração de estrutura documental (Docling, MinerU, etc.) dentro do pipeline
Acessilia. Este documento descreve o fluxo, os scripts e os resultados do
ciclo de comparação **Docling vs MinerU**.

Versão em inglês: [drbench.md](drbench.md)

## Visão geral

```
página (imagem) → Toolbox capability document.structure.extract (provider)
                → provider payload → árvore canônica (scripts/bench/core.py)
                → docstruct.export.markdown → predictions/<item>.md
                → docstruct.evaluation (métricas) → report.json, pages.jsonl, drilldown.csv
```

O fluxo roda pelo harness de benchmark (`python -m scripts.bench`, ver
[bench.md](bench.md)). O provedor é selecionado por `--provider` (ex.: `docling`,
`mineru`) e repassado ao `ToolboxStructureClient` do SDK (via `make_toolbox_client`). A Toolbox roteia para o
provider registrado em `providers-config.yaml` (endpoints `docling-serve` e
`mineru-serve`).

## Métricas

As métricas ficam em `docstruct.evaluation.metrics` e seguem o contrato EvalAI
do Dr.DocBench:

| Métrica | Escopo | Escala |
|---|---|---|
| `text_ed` | Levenshtein normalizado do texto da página | 0–1 (menor = melhor) |
| `reading_order` | Edit distance de sequência de blocos | 0–100 |
| `teds` | Similaridade de árvore (Zhang-Shasha) de tabelas HTML | 0–100 |
| `cdm` | F1 token-based de fórmulas LaTeX display | 0–100 |
| `overall` | Média dos componentes disponíveis × 100 | 0–100 |

Componentes sem objetos dos dois lados (ex.: página sem tabelas) são
**non-scorable** (`None`) e ficam de fora do overall — comportamento idêntico
ao EvalAI.

## Como rodar

```bash
uv run python -m scripts.bench download --dataset drdocbench --split dev --limit 100
uv run python -m scripts.bench run --dataset drdocbench --split dev --provider mineru --run mineru
uv run python -m scripts.bench run --dataset drdocbench --split dev --provider docling --run docling
uv run python -m scripts.bench score --dataset drdocbench --split dev --run mineru
```

Saídas em `var/bench/drdocbench/dev/<run>/`: `report.json` (agregado),
`pages.jsonl` e `drilldown.csv` (por página, piores primeiro). Em cluster
Slurm, `scripts/bench/slurm/bench.sbatch` sobe o provider e a Toolbox dentro do
job. Os scripts que produziram os resultados abaixo (`scripts/drbench/`) estão
na tag `drbench-2026-snapshot`; ver [drbench/experiments/CODE.md](drbench/experiments/CODE.md).

## Resultados do ciclo Docling vs MinerU (2026-09-15)

Amostra: 10 páginas do split `dev` com GT local (`adf0ea9c…_p32`–`p41`,
livro de arquitetura — texto corrido, sem tabelas/fórmulas).

| Métrica | MinerU | Docling | Δ |
|---|---|---|---|
| text_ed | 77.58 | 80.89 | −3.31 |
| reading_order | 78.11 | 81.42 | −3.31 |
| **overall** | **77.84** | **81.15** | **−3.31** |

Por página (overall):

| Página | MinerU | Docling | Melhor |
|---|---|---|---|
| p32 | 88.23 | 93.04 | docling |
| p33 | 90.97 | 89.36 | **mineru** |
| p34 | 55.66 | 71.71 | docling |
| p35 | 0.00 | 0.00 | empate (investigar GT) |
| p36 | 97.52 | 98.60 | docling |
| p37 | 96.97 | 96.49 | **mineru** |
| p38 | 94.30 | 91.88 | **mineru** |
| p39 | 82.99 | 82.82 | **mineru** |
| p40 | 95.60 | 96.25 | docling |
| p41 | 76.18 | 91.37 | docling |

### Leitura dos resultados

- **MinerU é comparável ao Docling** (gap de ~3 pontos no overall), vencendo em
  4 de 10 páginas.
- Falhas pontuais graves em p34 (−16.1) e p41 (−15.2): o MinerU descarta
  elementos que o Docling preserva (títulos curtos, legendas de figura,
  numeração de página) — ver comparação de árvores no notebook.
- `teds` e `cdm` ficaram **non-scorable**: a amostra não contém tabelas nem
  fórmulas. Para exercitá-las, ampliar a amostra com páginas do dataset que
  contenham esses objetos.
- p35 pontua 0 nos dois providers — suspeita de problema no GT, não nos
  providers.

### Comparação de árvores canônicas

A árvore canônica de cada provider pode ser inspecionada lado a lado:

```python
from scripts.bench.core import payload_to_canonical
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from backend.tools.toolbox_client import make_toolbox_client

client = make_toolbox_client(ToolboxStructureClient, provider="mineru")  # ou "docling"
try:
    result = await client.extract_structure(file_path=page_image)
finally:
    await client.close()
canonical = payload_to_canonical(result)
```

Notebook completo com a experimentação:
[notebooks/drdocbench/comparativo_docling_mineru.ipynb](notebooks/drdocbench/comparativo_docling_mineru.ipynb)

## Integração do MinerU na Toolbox

O provider `mineru` roda como serviço separado (`mineru-serve`, porta 5002) e
a Toolbox o consome via HTTP — sem runtime de ML na Toolbox:

- Config: `MINERU_SERVE_URL` no `.env.local` da Toolbox (resolvido por
  `expand_env()` em `providers-config.yaml`).
- Adapter: `acessilia_toolbox/providers/mineru.py` (chama `POST /file_parse`)
  + `mineru_document.py` (facade `middle_json` → contrato do normalizer:
  `iterate_items()`, `prov` com page_no 1-based, `pages` como dict).

## O que virou padrão no Acessilia

O trabalho de benchmark produziu capacidades que hoje são padrão no produto. A
regra é: **determinístico com evidência de ganho vira default; o que consome
modelo só entra quando a Toolbox expõe a capacidade.**

| Capacidade | Onde vive | Default |
|---|---|---|
| Chunking de verso/registro | `docstruct.fusion.verse` | ligado (`verse_chunk` 300) |
| Números de linha marginais | `docstruct.fusion.line_numbers` | ligado |
| Guarda de inundação de provider | `docstruct.fusion.flood` | ligado |
| Junção de cauda (`tj3`) | `docstruct.fusion.tailjoin` | ligado (`end/50/3/hdr`) |
| Guarda de repetição | `docstruct.fusion.repetition` | ligado |
| Cabeçalho/rodapé no fim | `docstruct.fusion.hf_end` | ligado |
| Normalização de texto | `docstruct.text.norm_fix` | ligado |
| Upscale antes do OCR | `docstruct.imaging.policy` | ligado |
| Correção de orientação | `docstruct.imaging.policy` | ligado |
| Juiz pareado por VLM | `docstruct.fusion.judge` | desligado (consome modelo) |
| Seleção/fusão de página | `docstruct.fusion.page_select` | desligado (consome modelo) |
| Especialista de tabela | `docstruct.fusion.table_specialist` | desligado (consome modelo) |
| Disciplina tune/holdout | `docstruct.evaluation.holdout` | sempre aplicada |

As capacidades também são obrigações de primeira classe no domínio PDDL v2.3
(`adjudicate-page`, `fuse-providers`, `chunk-verse`, `join-tail-blocks`, ...) e
tools dos agentes Agno (`FusionAgent`, `AdjudicationAgent`, `PageLevelAgent`,
`OrderAdjudicationAgent`, `TableSpecialistAgent`).

**Ressalva de método:** a melhor submissão, `hyb-v29-judge2-televm-adf-tj3`
(EvalAI 71.01, além do método do artigo), fez 87.33 no dev: um gap dev→test de
16.3 pontos. Dentro do método do artigo, o melhor é `differ-v15-hyb` (EvalAI
70.37, gap ~8), e o TEDS dele não transferiu (dev +5.9 → test +0.2). Nenhum
preset de benchmark é default. Os dois resultados estão congelados em
[`scripts/drbench/`](../scripts/drbench/README.pt-br.md). Ver
[`docs/drbench/experiments/RUNBOOK.pt-br.md`](drbench/experiments/RUNBOOK.pt-br.md).

## Relacionados

- [Notebook de onboarding Dr.DocBench](notebooks/drdocbench/initial.ipynb)
- [Architecture](architecture.md) — pipeline canônico
- [PMV Agno + PDDL](pmv_agno_pddl.md) — orquestração
- [Runbook de reprodução](drbench/experiments/RUNBOOK.pt-br.md) — retomar os testes de performance
- [Algoritmos do docstruct](docstruct_algorithms.pt-br.md) — as políticas determinísticas
