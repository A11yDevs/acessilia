# Dr.DocBench experiments (DocInsights 2026 shared task)

Snapshot of the experiment code that produced the EvalAI submissions of 2026-09-15 → 2026-09-18
(MinerU 58.09 → differ-v2 63.15 → differ-v12 69.82). The runnable copy lives in the experiment
workspace `/raid/user_marcospaulo/drdocbench` (DGX cluster, Slurm partition `h100n2`), with this
layout:

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

Scripts and sbatch files therefore reference `$WS/scripts/<name>.py` and `runs/...` relative to `<WS>`,
and some contain the absolute `/raid/user_marcospaulo/...` prefix. They are kept verbatim here for
reproducibility of the reported numbers; adapt `WS`/`env.sh` before running elsewhere.

## Contents

| dir | what |
|---|---|
| `differ/` | `tree_differ_v2.py` — bbox-aware block-level merge of Docling + MinerU (`blocks.json`), the system behind every `differ-v*` submission; `tree_differ_v1.py` — text-only predecessor (paper, 72.8 on dev-120); `adjudicate_v0/v1.py` — page-level selectors (paper, 74.0); `orient_pages.py` + `overlay_predictions.py` — rotated-page detection and re-inference overlay; `postprocess_md.py`, `rerender_from_payloads.py`, `replay_mineru_manifests.py` — re-serialisation utilities |
| `eval/` | wrappers around the official evaluator (`repos/DrDocBench`, md2md, 1-page windows): `build_official_pred*.py`, `official_summary.py`, `official_window_summary.py`; local approximate scorer `eval_local.py`; `paired_compare.py`; `ledger_append.py`; `make_dev_subset.py` (dev-120, seed 13); `fig3_delta_hist.py` |
| `analysis/` | evaluator drill-downs used for the lever design: `drilldown_md2md.py`, `text_loss_taxonomy.py`, `unmatched_by_category.py`, `gt_decor_order.py`, `gt_md_inventory.py`, `provider_block_compare.py`, `ro_decompose.py`, `simulate_levers.py`, `simulate_text_policy.py` |
| `submission/` | `build_submission_manifest.py` (EvalAI jsonl zip + validation), `build_all_submissions.sh` |
| `slurm/` | all sbatch jobs (inference, differ variants, official eval, zip build, CDM env, VLM) + `env.sh` (caches under `/raid`) |
| `variants/` | `variants_v*.txt` — flag sets evaluated per cycle (`name|args` per line, consumed by `slurm/differ_variants.sbatch`) |
| `toolbox_shim/` | `sitecustomize.py` injected into the toolbox venv during inference |
| `pages/` | page-level hybrid (v24 → v31): `vlm_page_ocr.py` (whole-page transcription by a VLM), `vlm_page_select.py` / `page_select.py` / `page_fuse.py` (GT-free choice between candidate pages), `vlm_page_judge.py` (Qwen3-VL judge, both orders, first-token probability), `dots_page_ocr.py` / `dsocr_page_ocr.py` / `teleocr_page_ocr.py` (extra whole-page sources: dots.ocr, DeepSeek-OCR, TeleOCR), `dots_page_select.py`, `pagenum_add.py`, `rep_guard.py`, `dedup_blocks.py`, `vlm_reseg.py`, `word_vote.py`, `loop_post.py`, and the tail-join post-process `tailjoin3.py` (+ `pnpos.py`, `tailjoin.py`) |

Experiment logs and decisions are in `docs/drbench/experiments/` (PLAN.md, SUBMISSIONS.md, JOBS.md,
LEDGER-dev120.md, LEDGER-dev986.md, dev-120 subset ids/json, per-page csvs).

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
predictions) is stored in this repo; all paths point at the local workspace.
