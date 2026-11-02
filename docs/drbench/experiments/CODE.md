# Experiment code — Dr.DocBench (DocInsights 2026)

> Brazilian Portuguese version: [versão pt-BR](CODE.pt-br.md)

The code that produced the EvalAI submissions of 2026-09-15 → 2026-09-18
(MinerU 58.09 → differ-v2 63.15 → differ-v12 69.82) is no longer on the main
branches. It is preserved, exactly as it ran, at the tag
[`drbench-2026-snapshot`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench); every link below points there. To run it, follow
the [runbook](RUNBOOK.md).

The submitted results themselves (the best submission and the paper's experiment, frozen with
their EvalAI scores and a script to check and replay them) are in
[`scripts/drbench/`](../../../scripts/drbench/README.md), the path the paper cites.

What became part of the product lives elsewhere now:

- the algorithms, as pure functions in [`libs/docstruct`](../../../libs/docstruct/README.md) (column *Now in* below);
- measuring the core on a benchmark, in the harness `python -m scripts.bench` ([docs/bench.md](../../bench.md)),
  with its Slurm jobs in `scripts/bench/slurm/`.

## Contents of the snapshot

| Directory | What | Now in |
|---|---|---|
| [`differ/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/differ) | [`tree_differ_v2.py`](https://github.com/A11yDevs/acessilia/blob/drbench-2026-snapshot/scripts/drbench/experiments/differ/tree_differ_v2.py): bbox-aware block-level merge of Docling + MinerU (`blocks.json`), the system behind every `differ-v*` submission; `tree_differ_v1.py`: text-only predecessor (paper, 72.8 on dev-120); `adjudicate_v0/v1.py`: page-level selectors (paper, 74.0); `orient_pages.py` + `overlay_predictions.py`: rotated-page detection and re-inference overlay; `postprocess_md.py`, `rerender_from_payloads.py`, `replay_mineru_manifests.py`: re-serialisation | `docstruct.fusion.differ`, `.similarity`, `.noise`, `.verse`, `.line_numbers`, `.flood`, `.adjudication`; `docstruct.text.normalize`, `.norm_fix`; `docstruct.imaging.policy` (orientation) |
| [`eval/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/eval) | wrappers around the official evaluator (`build_official_pred*.py`, `official_summary.py`, `official_window_summary.py`); local scorer `eval_local.py`; `paired_compare.py`; `ledger_append.py`; `make_dev_subset.py` (dev-120, seed 13); `fig3_delta_hist.py`; frozen replay (`frozen_*.py`, `replay_*.py`) | `docstruct.evaluation.metrics`, `.markdown`; official tree: `DrDocBench.build_official_tree` + `scripts/bench/slurm/eval_official.sbatch` |
| [`analysis/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/analysis) | evaluator drill-downs behind the lever design: `drilldown_md2md.py`, `text_loss_taxonomy.py`, `unmatched_by_category.py`, `gt_decor_order.py`, `gt_md_inventory.py`, `provider_block_compare.py`, `ro_decompose.py`, `simulate_levers.py`, `simulate_text_policy.py`, `block_oracle.py` | `docstruct.fusion.oracle` (block oracle); the rest is analysis, kept at the tag |
| [`pages/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/pages) | page-level hybrid (v24 → v31): `vlm_page_ocr.py`, `vlm_page_select.py` / `page_select.py` / `page_fuse.py`, `vlm_page_judge.py` (Qwen3-VL judge, both orders, first-token probability), `dots_page_ocr.py` / `dsocr_page_ocr.py` / `teleocr_page_ocr.py`, `pagenum_add.py`, `rep_guard.py`, `dedup_blocks.py`, `vlm_reseg.py`, `word_vote.py`, `loop_post.py`, `tailjoin3.py` (+ `pnpos.py`, `tailjoin.py`) | `docstruct.fusion.page_select`, `.judge`, `.repetition`, `.tailjoin`, `.hf_end`, `.table_specialist` |
| [`loop/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/loop) | the improvement cycles of [LOOP.md](LOOP.md): `agent2/` (fast scorer, support filter), block selection (`sel_feats.py`, `sel_apply.py`, `sel_ana.py`, `blk/`, `blk_sel.py`), `join_lines.py`, `dm_pages.py`, `cmp_sub.py`, `verse-merge/` | `docstruct.evaluation.holdout` (tune/holdout discipline); `docstruct.fusion.verse` |
| [`variants/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/variants) | `variants_v*.txt`: flag sets evaluated per cycle (`name\|args` per line, consumed by `slurm/differ_variants.sbatch`) | `docstruct.policy.FusionPolicy` |
| [`submission/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/submission) | `build_submission_manifest.py` (EvalAI jsonl zip + validation), `build_all_submissions.sh` | `python -m scripts.bench submit --dataset drdocbench` |
| [`slurm/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/slurm) | every sbatch job (inference, differ variants, official eval, zip build, CDM env, VLM) + `env.sh` | generic jobs in `scripts/bench/slurm/` (`setup`, `bench`, `eval_official`) and the VLM provider profile `providers-config-vlm.yaml`; the experiment-specific ones stay at the tag |
| [`toolbox_shim/`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench/experiments/toolbox_shim) | `sitecustomize.py` patching `MineruDocument` in the Toolbox process | fixed in the Toolbox (`MineruDocument.iterate_items`); no longer needed |
| top level ([`run_pipeline.py`](https://github.com/A11yDevs/acessilia/blob/drbench-2026-snapshot/scripts/drbench/run_pipeline.py), `markdown_converter.py`, `eval_run.py`, `download_gt.py`, `build_submission.py`, `page_record.py`) | the MVP runner: Toolbox page → canonical tree → `*.drbench.md`, local scoring, GT download, EvalAI zip | `scripts/bench` (`core.py`, `datasets/drdocbench.py`) and `docstruct.export.markdown` |

## Workspace the jobs expect

The scripts ran in an experiment workspace on the DGX cluster (Slurm partition `h100n2`):

```
<WS>/
  repos/acessilia, repos/acessilia-toolbox, repos/DrDocBench   # this repo, toolbox, official evaluator
  data/hf/dev/<SUBJECT>/<doc>/{images,mds}                      # HF dev split (GT)
  data/evalai/drdocbench-evaluation-v4/                          # EvalAI test images + manifest (509 pages)
  scripts/*.py                                                   # == experiments/{differ,eval,analysis,submission}/*.py (flat)
  runs/slurm/*.sbatch                                            # == experiments/slurm/
  runs/<split>/<provider>/predictions/*.{drbench.md,blocks.json} # provider outputs and merged predictions
  runs/evalai/<run>/submission/submission.zip                    # EvalAI zips
```

`slurm/env.sh` is parameterised (`WS`, `CACHE_ROOT`; `OPT`/`CDM_PYTHON` in `cdm_env.sh`), and the Python
helpers read `DRBENCH_WS`, `DRBENCH_FULL`, `DRBENCH_EVALUATOR` and `DRBENCH_GT`, so the jobs run on
another cluster after exporting those variables. Submit from `$WS`: `#SBATCH --output` is relative to it.

## Final differ arguments (submission differ-v13-pnt-ft-20260918)

```
tree_differ_v2.py --docling runs/evalai/docling-v3+rot/predictions --mineru runs/evalai/mineru-v3+rot/predictions \
  --lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto \
  --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 \
  --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --formula-text
```

## Page-level hybrid and tail-join (v24 → v31)

Beyond the block-level differ, the last stage works on whole pages: Docling × MinerU (differ) stays the base;
a Qwen3-VL page transcription, dots.ocr and TeleOCR are extra candidates; a Qwen3-VL-32B judge
(`pages/vlm_page_judge.py`) picks between two pages and `pages/tailjoin3.py` joins short trailing blocks
according to where the page number sits (bottom: keep the number last; top/unknown: join). Dev gain of
the tail-join: +1.0 mean of text and reading order (86.33 → 87.33).

Pipelines that use TeleOCR, the judge or dots.ocr go **beyond the paper's method** (Docling × MinerU only) and
must be declared as external models in the technical report. No challenge data (GT markdown, page lists,
predictions) is stored in this repository.
