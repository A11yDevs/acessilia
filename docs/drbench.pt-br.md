# Dr.DocBench — Benchmark de extração de estrutura

Dr.DocBench é a shared task de referência usada para avaliar provedores de
extração de estrutura documental (Docling, MinerU, etc.) dentro do pipeline
Acessilia. Este documento descreve o fluxo, os scripts e os resultados do
ciclo de comparação **Docling vs MinerU**.

Versão em inglês: [drbench.md](drbench.md)

## Visão geral

```
página (imagem) → Toolbox capability document.structure.extract (provider)
                → provider payload → árvore canônica (build_canonical_document)
                → canonical_to_drbench_md → predictions/<item>.drbench.md
                → eval_run (métricas) → reports/
```

O provedor é selecionado por `--provider` no `run_pipeline.py` (ex.: `docling`,
`mineru`) e repassado ao `ToolboxClient(provider=...)`. A Toolbox roteia para o
provider registrado em `providers-config.yaml` (endpoints `docling-serve` e
`mineru-serve`).

## Scripts (`scripts/drbench/`)

| Script | Função |
|---|---|
| `run_pipeline.py` | Gera predictions: baixa página, extrai via provider, converte para árvore canônica e escreve `*.drbench.md` |
| `eval_run.py` | Pontua predictions contra o ground truth (Text ED, Reading Order, TEDS, CDM, Overall) |
| `download_gt.py` | Download em lote do ground truth e imagens do dataset |
| `build_submission.py` | Monta submission no formato EvalAI |
| `markdown_converter.py` | Converte árvore canônica → markdown do benchmark |
| `page_record.py` | Registro canônico de página (`DrBenchPage`) |

## Métricas (`scripts/metrics/`)

As métricas vivem **dentro deste repositório** (migradas do pacote externo
`acessilia-metrics`), seguindo o contrato EvalAI do Dr.DocBench:

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
# 1. Gerar predictions (provider docling ou mineru)
python -m scripts.drbench.run_pipeline --split dev --sample 10 --provider mineru \
    --out-dir var/drbench/predictions-mineru
python -m scripts.drbench.run_pipeline --item <uuid>_p32 --provider docling

# 2. Avaliar
python -m scripts.drbench.eval_run \
    --predictions var/drbench/predictions-mineru \
    --gt-dir var/drbench/dev --provider mineru \
    --report var/drbench/reports/mineru.json
```

Saídas: `reports/<provider>.json` (agregado), `tracking.csv` (histórico),
`drilldown-<provider>.csv` (por página).

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
from scripts.drbench.run_pipeline import provider_payload_to_canonical
from backend.tools.toolbox_client import ToolboxClient

client = ToolboxClient(provider="mineru")  # ou "docling"
result = await client.extract_structure(file_path=page_image)
canonical = provider_payload_to_canonical(result)
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

## Relacionados

- [Notebook de onboarding Dr.DocBench](notebooks/drdocbench/initial.ipynb)
- [Architecture](architecture.md) — pipeline canônico
- [PMV Agno + PDDL](pmv_agno_pddl.md) — orquestração
