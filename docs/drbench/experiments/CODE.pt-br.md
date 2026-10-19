# Código dos experimentos — Dr.DocBench (DocInsights 2026)

> English version: [English guide](CODE.md)

O código que produziu as submissões ao EvalAI de 2026-09-15 → 2026-09-18
(MinerU 58.09 → differ-v2 63.15 → differ-v12 69.82) não está mais nos branches
principais. Ele está preservado, exatamente como rodou, na tag
[`drbench-2026-snapshot`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench); todos os links abaixo apontam para ela. Para
rodá-lo, siga o [runbook](RUNBOOK.pt-br.md).

Os resultados submetidos em si (a melhor submissão e o experimento do artigo, congelados com
os scores do EvalAI e um script para conferi-los e refazê-los) estão em
[`scripts/drbench/`](../../../scripts/drbench/README.pt-br.md), o caminho citado no artigo.

O que virou parte do produto mora em outro lugar agora:

- os algoritmos, como funções puras em [`libs/docstruct`](../../../libs/docstruct/README.pt-br.md) (coluna *Agora em* abaixo);
- a medição do core em um benchmark, no harness `python -m scripts.bench` ([docs/bench.pt-br.md](../../bench.pt-br.md)),
  com os jobs Slurm em `scripts/bench/slurm/`.

## Conteúdo do snapshot

| Diretório | O quê | Agora em |
|---|---|---|
| [`differ/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/differ) | [`tree_differ_v2.py`](https://github.com/A11yDevs/acessilia/blob/drbench-2026-snapshot/scripts/drbench/experiments/differ/tree_differ_v2.py): fusão block-level de Docling + MinerU com bbox (`blocks.json`), o sistema por trás de todas as submissões `differ-v*`; `tree_differ_v1.py`: antecessor só de texto (artigo, 72.8 no dev-120); `adjudicate_v0/v1.py`: seletores por página (artigo, 74.0); `orient_pages.py` + `overlay_predictions.py`: detecção de página rotacionada e sobreposição da re-inferência; `postprocess_md.py`, `rerender_from_payloads.py`, `replay_mineru_manifests.py`: re-serialização | `docstruct.fusion.differ`, `.similarity`, `.noise`, `.verse`, `.line_numbers`, `.flood`, `.adjudication`; `docstruct.text.normalize`, `.norm_fix`; `docstruct.imaging.policy` (orientação) |
| [`eval/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/eval) | wrappers do avaliador oficial (`build_official_pred*.py`, `official_summary.py`, `official_window_summary.py`); avaliador local `eval_local.py`; `paired_compare.py`; `ledger_append.py`; `make_dev_subset.py` (dev-120, seed 13); `fig3_delta_hist.py`; replay congelado (`frozen_*.py`, `replay_*.py`) | `docstruct.evaluation.metrics`, `.markdown`; árvore oficial: `DrDocBench.build_official_tree` + `scripts/bench/slurm/eval_official.sbatch` |
| [`analysis/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/analysis) | drill-downs do avaliador que embasaram o desenho das alavancas: `drilldown_md2md.py`, `text_loss_taxonomy.py`, `unmatched_by_category.py`, `gt_decor_order.py`, `gt_md_inventory.py`, `provider_block_compare.py`, `ro_decompose.py`, `simulate_levers.py`, `simulate_text_policy.py`, `block_oracle.py` | `docstruct.fusion.oracle` (oráculo de blocos); o resto é análise e fica na tag |
| [`pages/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/pages) | híbrido por página (v24 → v31): `vlm_page_ocr.py`, `vlm_page_select.py` / `page_select.py` / `page_fuse.py`, `vlm_page_judge.py` (juiz Qwen3-VL, nas duas ordens, probabilidade do primeiro token), `dots_page_ocr.py` / `dsocr_page_ocr.py` / `teleocr_page_ocr.py`, `pagenum_add.py`, `rep_guard.py`, `dedup_blocks.py`, `vlm_reseg.py`, `word_vote.py`, `loop_post.py`, `tailjoin3.py` (+ `pnpos.py`, `tailjoin.py`) | `docstruct.fusion.page_select`, `.judge`, `.repetition`, `.tailjoin`, `.hf_end`, `.table_specialist` |
| [`loop/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/loop) | os ciclos de melhoria do [LOOP.pt-br.md](LOOP.pt-br.md): `agent2/` (avaliador rápido, filtro de suporte), seleção de blocos (`sel_feats.py`, `sel_apply.py`, `sel_ana.py`, `blk/`, `blk_sel.py`), `join_lines.py`, `dm_pages.py`, `cmp_sub.py`, `verse-merge/` | `docstruct.evaluation.holdout` (disciplina tune/holdout); `docstruct.fusion.verse` |
| [`variants/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/variants) | `variants_v*.txt`: conjuntos de flags avaliados por ciclo (`nome\|args` por linha, lidos por `slurm/differ_variants.sbatch`) | `docstruct.policy.FusionPolicy` |
| [`submission/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/submission) | `build_submission_manifest.py` (zip jsonl do EvalAI + validação), `build_all_submissions.sh` | `python -m scripts.bench submit --dataset drdocbench` |
| [`slurm/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/slurm) | todos os jobs sbatch (inferência, variantes do differ, avaliação oficial, montagem de zip, ambiente CDM, VLM) + `env.sh` | jobs genéricos em `scripts/bench/slurm/` (`setup`, `bench`, `eval_official`) e o perfil de providers VLM `providers-config-vlm.yaml`; os específicos dos experimentos ficam na tag |
| [`toolbox_shim/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/toolbox_shim) | `sitecustomize.py` que corrigia o `MineruDocument` no processo da Toolbox | corrigido na Toolbox (`MineruDocument.iterate_items`); não é mais necessário |
| raiz ([`run_pipeline.py`](https://github.com/A11yDevs/acessilia/blob/drbench-2026-snapshot/scripts/drbench/run_pipeline.py), `markdown_converter.py`, `eval_run.py`, `download_gt.py`, `build_submission.py`, `page_record.py`) | o runner do MVP: página na Toolbox → árvore canônica → `*.drbench.md`, pontuação local, download do GT, zip do EvalAI | `scripts/bench` (`core.py`, `datasets/drdocbench.py`) e `docstruct.export.markdown` |

## Workspace que os jobs esperam

Os scripts rodaram num workspace de experimentos no cluster DGX (partição Slurm `h100n2`):

```
<WS>/
  repos/acessilia, repos/acessilia-toolbox, repos/DrDocBench   # este repo, toolbox, avaliador oficial
  data/hf/dev/<SUBJECT>/<doc>/{images,mds}                      # split dev do HF (GT)
  data/evalai/drdocbench-evaluation-v4/                          # imagens de teste do EvalAI + manifesto (509 páginas)
  scripts/*.py                                                   # == experiments/{differ,eval,analysis,submission}/*.py (achatado)
  runs/slurm/*.sbatch                                            # == experiments/slurm/
  runs/<split>/<provider>/predictions/*.{drbench.md,blocks.json} # saídas dos provedores e predições fundidas
  runs/evalai/<run>/submission/submission.zip                    # zips do EvalAI
```

O `slurm/env.sh` é parametrizado (`WS`, `CACHE_ROOT`; `OPT`/`CDM_PYTHON` no `cdm_env.sh`), e os
scripts Python leem `DRBENCH_WS`, `DRBENCH_FULL`, `DRBENCH_EVALUATOR` e `DRBENCH_GT`, então os jobs
rodam em outro cluster depois de exportar essas variáveis. Submeta a partir de `$WS`: o `#SBATCH --output`
é relativo a ele.

## Argumentos finais do differ (submissão differ-v13-pnt-ft-20260918)

```
tree_differ_v2.py --docling runs/evalai/docling-v3+rot/predictions --mineru runs/evalai/mineru-v3+rot/predictions \
  --lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto \
  --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 \
  --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --formula-text
```

## Híbrido por página e tail-join (v24 → v31)

Além do differ block-level, a última etapa trabalha com páginas inteiras: Docling × MinerU (differ) continua
sendo a base; a transcrição de página do Qwen3-VL, o dots.ocr e o TeleOCR são candidatos extras; um juiz
Qwen3-VL-32B (`pages/vlm_page_judge.py`) escolhe entre duas páginas e o `pages/tailjoin3.py` junta blocos
finais curtos conforme a posição do número de página (rodapé: o número fica por último; topo/desconhecido:
junta). Ganho do tail-join no dev: +1.0 na média de texto e ordem de leitura (86.33 → 87.33).

Pipelines que usam TeleOCR, o juiz ou o dots.ocr vão **além do método do artigo** (só Docling × MinerU) e
precisam ser declarados como modelos externos no relatório técnico. Nenhum dado do desafio (markdown de GT,
listas de páginas, predições) é guardado neste repositório.
