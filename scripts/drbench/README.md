# Acessília at the Dr.DocBench shared task (DocInsights 2026)

> Brazilian Portuguese version: [versão pt-BR](README.pt-br.md)

This directory is the permanent entry point for Acessília's participation in the
[Dr.DocBench](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench) shared task of
DocInsights 2026: page-level document parsing to Markdown, scored on EvalAI by text edit distance,
table TEDS, formula CDM and reading order (Overall = per-page mean of the available components).

It keeps the two results below frozen, a script to check and reproduce them (`run.sh`), and the
software versions behind them ([VERSIONS.md](VERSIONS.md)). The experiment code itself is preserved,
exactly as it ran, at the tag [`drbench-2026-snapshot`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench);
what each script does and where its algorithm went in the product is in
[docs/drbench/experiments/CODE.md](../../docs/drbench/experiments/CODE.md).

## Results

| | Run | Method | EvalAI Overall | Text ED ↓ | Table TEDS | Formula CDM | Reading order |
|---|---|---|---|---|---|---|---|
| **Best submission** | `hyb-v29-judge2-televm-adf-tj3-20261009` | beyond the paper: multi-source with VLM judge (below) | **71.01** | 0.2708 | 56.16 | 0.16 | 75.87 |
| **Paper's experiment** | *pending* | Docling × MinerU (Tree Differ) | *pending* | | | | |

Test split: 509 pages (34 documents × up to 15 contiguous pages, 28 subjects).

## Best submission (71.01)

### Frozen artifacts — [`submissions/best/`](submissions/best/)

| File | What | SHA-256 |
|---|---|---|
| `submission.zip` | the zip submitted to EvalAI (downloaded as `6d9f2b09-19a3-4e5d-8483-56e1854f49c.zip`) | `08ec980d4bc9ec27acdd494c5c676830169c5506085f9f445bbc327470353a64` |
| `predictions.jsonl` (inside the zip) | 509 rows `{subject, document_id, page, markdown}` | `2b83be1409b50a4051e2081dffc401cf501631b018c7f56b2d31513a883b11e3` |
| `evalai-result.json` | the EvalAI result for that zip (downloaded as `a7f14c6c-c408-467f-9191-add3d582ab.json`; a Python literal, kept byte for byte) | `6b4d9e81dfff9168b8fc992a09eafdd8cfee360f375f8e49e80c3c76e534ee13` |

### How it was produced

All runs are in [SUBMISSIONS-LEADERBOARD.md](../../docs/drbench/experiments/SUBMISSIONS-LEADERBOARD.md);
the decisions, with their tune/holdout numbers, in [LOOP.md](../../docs/drbench/experiments/LOOP.md).
Jobs ran on Slurm partition `h100n2` (1 × H100); the job scripts are at the tag under
`scripts/drbench/experiments/slurm/`.

1. **Provider extraction**, with rotated pages detected (RapidOCR) and re-inferred straightened:
   Docling (`docling-serve` 1.32) and MinerU 3.4 `hybrid-engine` (the sources of `differ-v15-hyb`).
2. **Base line `differ-v29-adf`**:
   `tree_differ_v2.py` block-level fusion of the two providers with the `differ-v15-hyb` arguments, then
   Qwen3-VL-32B text adjudication and reading-order selection (`differ-v24-AOs`, job 34364);
   `loop_post --split-lines 150 --smallcaps` (v25); Qwen3-VL-32B whole-page selection where the providers
   disagree, with a commentary filter (v26b, job 34373); dots.ocr page selection and `rep_guard`
   (v28c, job 34413); `pagenum_add` (v29-pn); and one rotated 15-page document redone with dots.ocr on a
   straightened 3× copy (v29-adf, job 34433).
3. **Tele line `teleocr-up2m2-vm-fb-adf`**: TeleOCR whole-page parsing with pages < 800 px and
   800–1200 px upscaled 2× (job 34448), blocks merged guided by v29-pn (LOOP #42), v29 fallback where
   Tele is short (ratio 0.3, 24 pages), and the same dots.ocr document.
4. **Page choice `hyb-v29-judge2-televm-adf`** (LOOP #45): a Qwen3-VL-32B pairwise judge
   (`vlm_page_judge.py`, both orders, first-token probability) on pages where the two lines diverge.
   The Tele page is used when `pB > 0.5` in the judgement v29-adf vs Tele-vm-fb (job 34458), or, on pages
   that judgement did not cover, when `pB > 0.2` in the earlier judgement (LOOP #44): 87 of 509 pages.
5. **Tail-join `tj3`** (LOOP #51): `pnpos.py` takes the page-number position from the TeleOCR layout
   (dots.ocr as fallback); `tailjoin3.py SRC OUT POS 50 3 hdr` joins the short final blocks, or, with the
   number at the bottom, keeps them and moves the number last.
6. **Submission**: `build_submission_manifest.py` (rows in the official manifest order).

**External models.** Beyond Docling and MinerU, this result uses Qwen/Qwen3-VL-32B-Instruct-FP8
(adjudication, page selection, judge), XingChen-AGI/TeleOCR, dots-studio/dots.ocr and RapidOCR
(orientation). It goes beyond the paper's method and must be reported with them declared.

**Dev vs test.** The same pipeline scored 87.33 on the dev analogue (tune 90.60, holdout 83.11) and
71.01 on test: a 16.3-point gap, against 7.7 for `differ-v15-hyb` (dev 78.1, test 70.37). Part of it is
the test window (15 contiguous pages per document vs isolated dev pages).

### Reproduce

```bash
scripts/drbench/run.sh best verify              # hashes, 509 unique pages, EvalAI scores
scripts/drbench/run.sh best replay INPUTS_DIR   # steps 4–6 from frozen inputs, byte-for-byte check
scripts/drbench/run.sh best full                # steps 1–3: points to the GPU jobs (not bit-exact)
```

- **verify** needs only this directory.
- **replay** redoes steps 4–6, which use no model, with the tag's code and Python 3 alone, from the
  intermediate outputs of steps 1–3 and the two judgements, and compares the resulting
  `predictions.jsonl` with the frozen one byte for byte. Those inputs live on the cluster;
  [`collect_inputs.sh`](collect_inputs.sh) packages them (and the versions) and runs the replay there.
  **Status: the inputs bundle is not archived yet.**
- **full** reruns the GPU steps. GPU inference is not deterministic: compare scores, not hashes.

## Paper's experiment

*Pending.* This section will hold the paper's run, its frozen submission and EvalAI result in
`submissions/paper/`, and `run.sh paper`. Within the paper's method (Docling × MinerU), the best
confirmed submission in the records is `differ-v15-hyb-20260922`, EvalAI 70.37.

## See also

- [Reproduction runbook](../../docs/drbench/experiments/RUNBOOK.md) — environment, frozen replay, GPU costs
- [RESULTS.json](../../docs/drbench/experiments/RESULTS.json) — numbers and zip hashes of every submission
- [Benchmark harness](../../docs/bench.md) — how the core is measured on Dr.DocBench today
