# Runbook de reprodução — Dr.DocBench

> English version: [English](RUNBOOK.md)

Como reconstruir o ambiente, congelar uma execução, replayá-la e comparar os
resultados. Este é o ponto de entrada único para retomar os testes de performance.

## 0. O que é determinístico e o que exige modelo

| Passo | Determinístico? | Precisa de GPU? |
|---|---|---|
| Testes da biblioteca (`libs/docstruct/tests`) | sim | não |
| Testes do core (`tests/`) | sim | não |
| Differ / fusão sobre o JSON cru congelado | sim | não |
| Avaliação oficial (md2md, TEDS, CDM) | sim | não (CDM precisa do stack TeX) |
| Extração dos providers (Docling, MinerU) | não | sim (MinerU hybrid-VLM) |
| OCR VLM de página inteira (Qwen3-VL, dots.ocr, DeepSeek-OCR-2, TeleOCR) | não | sim |
| Juiz pareado por VLM | não | sim |
| Detecção de orientação (RapidOCR) | não | só CPU |

O replay (`frozen_replay.py`) **nunca roda OCR de novo**: ele consome o JSON cru
de inferência. É isso que torna uma execução registrada reproduzível sem GPU.

## 1. Reconstruir o ambiente

```bash
# Core + biblioteca + dependências de teste (pytest, numpy), pinados pelo lockfile;
# acrescente --extra drbench para o OpenCV (scripts/drbench/experiments/differ/orient_pages.py)
uv sync --frozen --extra dev

# Os testes da biblioteca devem passar sem o backend instalado
uv run pytest libs/docstruct/tests

# Testes do core (6 falhas pré-existentes em test_formula_enrichment.py e
# test_pddl_orchestrator.py são esperadas; 0 skips)
uv run pytest -m "not e2e"
```

O lockfile é `uv.lock` (90 pacotes). O `pyproject.toml` declara
`acessilia-docstruct` como fonte de caminho editável, então `uv sync` instala a
biblioteca a partir de `libs/docstruct`.

O workspace de experimentos é separado deste repositório. O `slurm/env.sh` é
parametrizado; sobrescreva as raízes para relocar:

```bash
WS=/my/workspace CACHE_ROOT=/my/cache source runs/slurm/env.sh
```

Layout esperado sob `$WS`:

```
repos/acessilia, repos/acessilia-toolbox, repos/DrDocBench
data/hf/dev/<SUBJECT>/<doc>/{images,mds,json}
data/evalai/drdocbench-evaluation-v4/images
runs/slurm/*.sbatch
```

## 2. Congelar uma execução

Escolha um spec em `scripts/drbench/experiments/eval/specs/`:

| Spec | Split | Páginas |
|---|---|---|
| `dev120.spec.json` | dev | 120 (seleção versionada) |
| `dev986.spec.json` | dev | 986 (gerar `pages.json`) |
| `test509.spec.json` | evalai | 509 (gerar `pages.json`) |

Os dois specs de split completo declaram um `pages_generator`; rode-o uma vez no
workspace:

```bash
python scripts/drbench/experiments/eval/make_replay_pages.py \
    --images-root $WS/data/hf/dev --out dev986-pages.json
```

Depois congele:

```bash
python scripts/drbench/experiments/eval/frozen_replay.py freeze \
    --spec scripts/drbench/experiments/eval/specs/dev986.spec.json \
    --out $WS/runs/replay/dev986-<label>
```

O congelamento registra: a seleção de páginas, os payloads crus dos providers, as
imagens, o ground truth, as exportações Git das duas variantes e do avaliador, o
lockfile, as revisões dos modelos e os hashes das fontes. Ele recusa working tree
sujo e recusa escrever dentro de um repositório de código.

## 3. Replayar e comparar

```bash
python scripts/drbench/experiments/eval/frozen_replay.py evaluate \
    --run $WS/runs/replay/dev986-<label> --require-zero-regressions
```

O replay escreve `per-page.csv`, `summary.json` e `REPORT.md`. O gate de qualidade
rejeita perdas por página e cobertura assimétrica de métricas, mesmo quando a
média melhora. `overall` é a métrica de ranking da competição (média por página
dos componentes disponíveis).

## 4. Custo de GPU de cada passo

Os jobs registrados rodaram em `h100n2` (1 GPU, 16 CPUs, 128 GB). Custos
aproximados:

| Passo | Job | Custo |
|---|---|---|
| Extração dos providers, dev-986 (Docling + MinerU) | `full_gpu.sbatch` | ~2 h GPU |
| MinerU hybrid-VLM, dev-986 + test-509 | `mineru_vlm.sbatch` | ~10 h GPU (3 estágios) |
| OCR VLM de página inteira (Qwen3-VL-32B), dev-986 | `vlm_page.sbatch` | ~4 h GPU |
| Parse de página TeleOCR, dev + test | `teleocr_page.sbatch` | ~3 h GPU |
| Juiz pareado por VLM, só páginas divergentes | `vlm_judge*.sbatch` | ~1 h GPU |
| Detecção de orientação (RapidOCR) | `orient.sbatch` | ~20 min CPU |
| Variantes do differ sobre o JSON cru congelado | `differ_variants.sbatch` | minutos, CPU |
| Avaliação oficial | `eval_official.sbatch` | ~30 min CPU (CDM precisa de TeX) |

O juiz só roda nas páginas onde as candidatas divergem (ratio < 0.97), o que é
~17% do split de test — por isso é barato em relação ao OCR completo.

## 5. O que verificar antes de promover um método

1. **Confirme no leaderboard.** O melhor de dev (87.33) nunca foi confirmado; o
   gap dev→test observado é de ~8 pontos. Ganho no dev não é resultado.
2. **Verifique qual métrica se moveu.** O TEDS não transferiu (dev +5.9 → test
   +0.2); o ganho real no test veio da ordem de leitura com a fonte MinerU
   hybrid-VLM.
3. **Respeite o holdout.** O split é por documento (`md5(doc) % 3`). O aceite
   exige Δtune ≥ +0.10, Δhold ≥ 0 e nenhuma métrica −0.3.
4. **Rode o frozen replay** como gate de regressão antes de submeter.

## 6. Artefatos congelados

`docs/drbench/experiments/RESULTS.json` guarda os números, os hashes dos zips de
submissão e a composição de cada execução. As saídas em si vivem fora do
repositório (no scratch do cluster).

## 7. Referências

- `scripts/drbench/experiments/eval/FROZEN_REPLAY.md` — formato do spec e disciplina
- `scripts/drbench/experiments/README.md` — layout do workspace e relocação
- `docs/drbench/experiments/SERVICES-LOOP.md` — serviços iniciados dentro de cada job
- `docs/drbench/experiments/LOOP.md` — o loop de experimentos e suas decisões
- `docs/drbench/experiments/SUBMISSIONS-LEADERBOARD.md` — submissões e scores
