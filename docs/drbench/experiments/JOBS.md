# Slurm jobs — Dr.DocBench (partição h100n2, nó dgx-H100-02)

Todos os jobs fazem `source runs/slurm/env.sh` (caches em `$CACHE_ROOT`). Logs em `runs/slurm/logs/<name>_<jobid>.log` (+ `_docling.log` / `_mineru.log` / `_toolbox.log` para os serviços). Scripts: `setup.sbatch`, `pipeline.sbatch` (genérico, reentrante), `full_gpu.sbatch`.

| Job | Nome | Recursos | Propósito | Status (2026-09-15 ~16:40 UTC) |
|---|---|---|---|---|
| 32559 | drb-setup | CPU 16c/64G/2h | venvs (toolbox, docling-serve, mineru, acessilia), modelos docling+mineru, dev split HF | COMPLETED — 986 json/md/jpg |
| 32560 | drb-smoke-docling | CPU 8c/32G/40m | smoke 2 págs EvalAI, provider docling | COMPLETED ok=2 fail=0, 16 s/pág |
| 32561 | drb-smoke-mineru | CPU 8c/32G/40m | smoke mineru (sem shim) | FAILED 0/2 — bug toolbox (ver abaixo) |
| 32562–32564 | drb-subset (srun) | CPU 2c/8G/10m | `scripts/make_dev_subset.py` → 120 págs | COMPLETED |
| 32565 | drb-smoke-mineru | CPU 8c/32G/40m | smoke mineru com shim v1 | COMPLETED ok=2 fail=0, 14 s/pág (1 parágrafo por linha) |
| 32566 | drb-dev-docling | CPU 32c/128G/6h | subset dev 120 págs, docling → `runs/dev/docling/predictions` | RUNNING |
| 32567 | drb-dev-mineru | CPU 32c/128G/8h | (shim v1) | CANCELLED — substituído por 32570 |
| 32568 | drb-gpu-full | GPU 1 + 16c/128G/12h | `full_gpu.sbatch`: docling+mineru nas 509 EvalAI, depois dev completo (986) | PENDING (fila GPU) |
| 32569 | drb-smoke-mineru | CPU 8c/32G/40m | smoke mineru com shim v2 (linhas fundidas em parágrafo) | ver `squeue` |
| 32570 | drb-dev-mineru | CPU 32c/128G/8h | subset dev 120 págs, mineru → `runs/dev/mineru/predictions` | ver `squeue` |

## Como submeter
```bash
cd "$WS"
sbatch -c 32 --mem 128G --time 06:00:00 --job-name drb-dev-docling \
  --export=ALL,PROVIDER=docling,IMAGES_ROOT=$PWD/runs/dev/subset-images,OUT_DIR=$PWD/runs/dev/docling/predictions,SAMPLE=0 \
  runs/slurm/pipeline.sbatch
# ITEMS_FILE=<lista de ids> opcional; SAMPLE=N limita; reentrante (pula <id>.drbench.md existentes)
```

## Bugs / workarounds
- **acessilia-toolbox** `src/acessilia_toolbox/core/normalization/builder.py:188` chama `document.iterate_items(...)` e `:460` `document.pages.items()`, mas `src/acessilia_toolbox/providers/mineru_document.py::MineruDocument` não implementa `iterate_items` e `pages` retorna `list` → HTTP 500 em `document.structure.extract` com provider mineru. Workaround sem tocar no repo: `scripts/toolbox_shim/sitecustomize.py` carregado via `PYTHONPATH` só no processo uvicorn da toolbox (ver `pipeline.sbatch`). Mapeia blocos MinerU → labels Docling (`text/section_header/table/formula/...`), page_no 1-based, tabela como HTML, fórmula como `$$…$$`.
- **Docling models** foram baixados para `~/.cache/docling/models` pelo `docling-tools models download`; movidos para `$CACHE_ROOT/docling/models` (symlink na home) e `DOCLING_ARTIFACTS_PATH` em `env.sh`.
- **mineru.json** gerado em `~/mineru.json` com `models-dir.pipeline` apontando para o HF cache em `/raid`; cópia em `$CACHE_ROOT/mineru/mineru.json` (`MINERU_TOOLS_CONFIG_JSON`). Pipeline usa `MINERU_MODEL_SOURCE=local`.
- **acessilia** `scripts/drbench/run_pipeline.py` não é reentrante e roda 1 página por invocação com `--item`; o sbatch faz o loop e o skip.
- Observado no smoke docling (`runs/smoke/docling/predictions/*_p17.drbench.md`): título e parágrafos duplicados na saída (ex. "# DAVID LEWIS DAVID LEWIS", parágrafo "son is committed…" repetido). Suspeito: `scripts/drbench/run_pipeline.py:_extract_text_from_provider` / `backend/pipeline/canonical_builder.py` — investigar (afeta Edit Distance).
| 32571 | drb-dev-docling-focr | h100n2, CPU 32c/128G, 4h, afterany:32566 | Docling com `force_ocr=true` (patch local em toolbox providers/docling.py) no subset dev → runs/dev/docling-forceocr | COMPLETED 120/120 |
| 32573–32574, 32576 | drb-eval-local (srun) | CPU 8c/32G | `scripts/eval_local.py` (métricas locais) para docling, mineru, docling-forceocr → `runs/dev/<run>/reports/local*.{json,csv}` | COMPLETED (~5 s/run) |
| 32577, 32579 | drb-eval-summary (srun) | CPU 4c/16G | `scripts/eval_summary.py` → `runs/dev/summary.{md,json}`, `delta_per_page.csv`, `agreement_per_page.csv` | COMPLETED |
| 32578 | drb-eval-official | CPU 8c/32G/1.5h | `runs/slurm/eval_official.sbatch`: venv `repos/DrDocBench/.venv` (deps OmniDocBench, sem CDM/TeX), fig3, avaliador oficial `multipage_pdf_validation.py` (janela 1 pág.) nas 3 runs → `runs/dev/<run>/reports/official_metric_result.json`, `runs/dev/official/result/` | FAILED (result/ ausente; venv criado OK) |
| 32580 | drb-eval-official | CPU 8c/32G | re-run de 32578 (faltava `mkdir result/`) — COMPLETED em ~30 s: avaliador oficial nas 3 runs (sem CDM); `runs/dev/official/result/*`, `runs/dev/<run>/reports/official*.json`, `paper/figures/fig3_delta_hist.pdf` | COMPLETED |
| 32581+ | drb-eval-summary / drb-eval-official-sum (srun) | CPU 2–4c | `scripts/eval_summary.py` + `scripts/official_summary.py` → `runs/dev/summary.md` final | COMPLETED |
| 32583 | drb-test509-docling | CPU 32c/128G, 5h | Docling force-OCR nas 509 págs de teste → runs/evalai/docling-forceocr | submetido 17:58 UTC |
| 32584 | drb-test509-mineru | CPU 32c/128G, 5h | MinerU nas 509 págs de teste → runs/evalai/mineru | submetido 17:58 UTC |
| 32585 | drb-adjudicator-v0 | CPU 4c/16G/30m, `--dependency=afterany:32584` | `runs/slurm/adjudicator_v0.sbatch`: `scripts/adjudicate_v0.py` (v0 e v0b) sobre runs/dev/{docling-forceocr,mineru} → `runs/dev/adjudicator-v0{,b}/predictions` (+`decisions.csv`); `eval_local.py` + avaliador oficial (`end2end_nocdm.yaml`) → `runs/dev/adjudicator-v0{,b}/reports/{local,official}.json`; `eval_summary.py`/`official_summary.py`/`adjudicator_summary.py` (5 runs) → `runs/dev/summary.md` (seção "Adjudicator v0"); por fim `scripts/build_all_submissions.sh` (zips EvalAI para docling-forceocr/mineru/adjudicator-v0, só se ambos com 509 págs) | PENDING (QOS 2 jobs) — conferir `tail -f runs/slurm/logs/drb-adjudicator-v0_32585.log` |
| 32586/32587 | drb-build-sub (srun) | h100n2 -c4 16G 20min | build+validate 3 submission.zip (1ª tentativa falhou: builder da toolbox rejeita p0/subject vazio → scripts/build_submission_manifest.py) | concluído 19:21 UTC |
| 32594 | drb-differ-v1 | h100n2 -c4 16G 30min | Tree Differ v1 (text-only block merge) dev subset + eval local/oficial | 21:24 UTC |
| 32626 | drb-setup-cdm | h100n2 -c8 32G 3h | `runs/slurm/setup_cdm.sbatch`: node portátil + TeX Live 2025 scheme-small (xelatex, xeCJK) + magick shim + Source Han Sans em $CACHE_ROOT/opt → `runs/slurm/cdm_env.sh`; habilita CDM local (`end2end_full.yaml`) | 2026-09-16 |
| 32631 | drb-eval adjudicator-v0-notitle-20260916 | h100n2 -c8 32G 2h | validação do `runs/slurm/eval_run.sbatch` (S0.1): reproduz 74.0 (+0.06 c/ strip de título placeholder) → LEDGER.md | concluído 14:15 UTC |
| 32632 | drb-dev-docling-fix | h100n2 -c32 128G 3h | Docling force-OCR dev-120 com `--save-raw` → `runs/dev/docling-fix-20260916/predictions/*.{drbench.md,blocks.json,provider.json}`. ATENÇÃO: código de run_pipeline mudou durante o job (páginas 1–60 caminho texto, resto caminho estruturado) → predições NÃO avaliar; usar só os `.provider.json` e re-renderizar (`scripts/rerender_from_payloads.py`) como `docling-v2-20260916` | 2026-09-16 14:26 UTC |
| 32633 | drb-replay-mineru mineru-v2-20260916 | h100n2 -c8 32G 2h | `runs/slurm/replay_mineru.sbatch`: manifests a partir dos middle.json do MinerU já em disco (`scripts/replay_mineru_manifests.py`, mapeia por sha256 da imagem) → re-render com mapeamento canônico estruturado (`scripts/rerender_from_payloads.py`) → eval_run (oficial+local+ledger). Testa correção do bug prosa→$$ | PENDING (QOS) |
| 32634 | drb-rerender mineru-v3-20260916 | CPU 8c/32G 1.5h | re-render mineru-raw com promoção de inline math + eval vs mineru |
| 32635 | drb-rerender docling-v2-20260916 | CPU 8c/32G 1.5h (after 32634) | re-render payloads docling-fix + eval vs docling-focr |
| 32641 | drb-dev-docling-v3 | h100n2 -c32 128G 3h CPU | Docling force-OCR dev-120 com toolbox@e2f9ce6 (table_ast de table_cells) + acessilia@d9c57d4 → runs/dev/docling-v3-20260916/predictions (--save-raw). Avaliar com eval_run BASELINE=docling-v2-20260916 | 2026-09-16 15:13 UTC |
| 32642 | drb-replay-mineru test mineru-v3-20260916 | CPU 8c/32G 2h | replay offline dos 509 middle.json (toolbox output) → runs/evalai/mineru-v3-20260916/predictions com acessilia@d9c57d4 | 2026-09-16 15:17 UTC |
| 32641 | (cancelado a 27/120 — substituído por 32644 com toolbox grid fix) | | | |
| 32644 | drb-dev-docling-v3 | h100n2 -c32 128G 3h CPU | Docling force-OCR dev-120 com toolbox@6be3685 (table_ast de grid) → runs/dev/docling-v3-20260916/predictions (--save-raw) | 2026-09-16 15:19 UTC |
| 32645 | drb-test509-docling-v3 | CPU 32c/128G 4h | Docling force-OCR nas 509 págs de teste com toolbox@6be3685 + acessilia@d9c57d4 (--save-raw) → runs/evalai/docling-v3-20260916/predictions | 2026-09-16 15:20 UTC |
| 32646 | drb-eval mineru-v3-20260916 CDM=1 | CPU 8c/32G 2h | primeira avaliação dev com CDM funcional (skimage 0.22) | 2026-09-16 15:21 UTC |
| 32647 | drb-eval docling-v3-20260916 | CPU 8c/32G (after 32644) | eval oficial+local, baseline docling-v2 | 2026-09-16 15:23 UTC |
| 32648 | drb-adjudicate adjudicator-v1-20260916 | CPU 8c/32G (after 32647) | adjudicate_v1 (prefs mineru) docling-v3 + mineru-v3, baseline adjudicator-v0 | 2026-09-16 15:23 UTC |
| 32649 | drb-adjudicate adjudicator-v1d-20260916 | CPU 8c/32G (after 32648) | adjudicate_v1 --table-pref docling --formula-pref docling, baseline adjudicator-v1 | 2026-09-16 15:23 UTC |
| 32650 | drb-adjudicate differ-v2-20260916 | CPU 8c/32G (after 32649) | tree_differ_v2 (bbox+texto, lam 0.5 tau 0.6) docling-v3 + mineru-v3, baseline adjudicator-v1 | 2026-09-16 15:50 UTC |
| 32653 | drb-adjudicate differ-v2-20260916 (test) | CPU 8c/32G | tree_differ_v2 lam0.5 tau0.6 sobre test-509 docling-v3 + mineru-v3 → runs/evalai/differ-v2-20260916/predictions | 2026-09-16 16:49 UTC |
| 32654→32655 (32654 cancelado, GRID errado) | drb-differ-grid | CPU 8c/32G 3h | grid lam/tau tree_differ_v2 dev-120 (0.3:0.6 0.7:0.6 0.5:0.5 0.5:0.7), baseline differ-v2 | 2026-09-16 16:50 UTC |
| 32666 | drb-adjudicate differ-v2-minlen0 | CPU 8c/32G | differ-v2 sem descartar blocos Docling curtos (--min-len 0; nº de página/cabeçalhos), baseline differ-v2 | 2026-09-16 18:29 UTC |
| 32668→32670 (32668 cancelado; agora --min-len 0) | drb-adjudicate differ-v2 (dev-full) | CPU 8c/32G | tree_differ_v2 λ0.5 τ0.6 min_len0 sobre runs/dev-full/{docling,mineru} (986 pág, GPU job 32568) → runs/dev-full/differ-v2 | 2026-09-16 18:42 UTC |
| 32669→32671 | drb-eval-full | CPU 8c/48G 4h (afterok 32670) | avaliador oficial dev-986 janelas 1 pág e documento (15 pág) para differ-v2, mineru, docling → runs/dev-full/LEDGER.md | 2026-09-16 18:42 UTC |
| 32672 | drb-adjudicate differ-v2-minlen0 (test) | CPU 8c/32G | tree_differ_v2 λ0.5 τ0.6 min_len0 sobre test-509 docling-v3 + mineru-v3 → runs/evalai/differ-v2-minlen0-20260916 | 2026-09-16 18:43 UTC |
| 32675 | drb-eval-full md2md | CPU 8c/48G | dev-986 protocolo md2md (GT = mds/*.md curado, = contrato EvalAI single-page-md2md) para differ-v2, mineru, docling → runs/dev-full/LEDGER.md (*-w1-md2md) | 2026-09-16 19:02 UTC | — DONE 7min: differ-v2 66.4, mineru 62.5, docling 56.3 (evalai_style md2md w1); bate com EvalAI 63.15
| 32677, 32678 | srun inventário | CPU 2c/8G | contagem de tipos de bloco (docling: group=710 md="list", unknown=145 md="group", page_header 887, page_footer 457; mineru: footnote 187, caption 116) e páginas com $$ (differ-v2 dev = 26 = mineru) | 2026-09-16 19:30 UTC |
| 32679 | drb-differ-variants | CPU 8c/48G 2h | tree_differ_v2 variantes v3a-clean (drop docling group,unknown,page_header,page_footer), v3b-nocap (+caption docling, caption+footnote mineru), v3c-fallback (v3a + --garbage-fallback 0.25) em dev-986 → runs/dev-full/{v3a-clean,v3b-nocap,v3c-fallback} + eval md2md w1 → LEDGER | 2026-09-16 19:40 UTC | **FALHOU: Slurm --export quebra nas vírgulas → só drop group; cancelado.** Relançado como 32680 via VARIANTS_FILE=runs/dev-full/variants_v3.txt (separador +) |
| 32680 | drb-differ-variants (relançado) | CPU 8c/48G | dev-986 md2md: v3a-clean 66.8 (text 77.7 RO 60.3) · v3b-nocap 66.1 · v3c-fallback 66.7 (7 págs fallback) vs differ-v2 66.4 | 2026-09-16 19:43 UTC |
| 32681 | drb-differ-variants v3d/v3e | CPU 8c/48G | ablação: v3d-footer (drop group+unknown+page_footer), v3e-junk (drop group+unknown) em dev-986 md2md | 2026-09-16 20:00 UTC | DONE: v3d-footer 64.5 (RO 53.3!) · v3e-junk 66.4 → só header+footer juntos ajudam RO |
| 32682 | drb-adjudicate differ-v3a-clean (test) | CPU 8c/32G | tree_differ_v2 min_len0 + drop docling group+unknown+page_header+page_footer sobre test-509 docling-v3 + mineru-v3 → runs/evalai/differ-v3a-clean-20260916 | 2026-09-16 19:56 UTC |
| srun drb-zip | zip differ-v3a-clean | CPU 2c/8G | build_submission_manifest + validate (valid, 509) → runs/evalai/differ-v3a-clean-20260916/submission/submission.zip sha 5c430b93… | 2026-09-16 20:10 UTC |
| 33037–33038 | srun smoke/GT-stats | CPU 2c/8G/10m | smoke `tree_differ_v2 --verse-chunk/--line-numbers/--table-eq` em 3 págs POETRY; distribuição de tamanho dos blocos de verso no GT (709 blocos, 80% ≤300 chars, mediana 158) | 2026-09-22 | DONE |
| 33039 | drb-differ-v15 | CPU 8c/48G/2h30 | `differ_variants.sbatch` com `runs/dev-full/variants_v15.txt` (7 variantes: fonte mineru-hyb+rot, verse-chunk 150/200/300, line-numbers, table-eq, nofuse; docling+rot) + eval md2md de `mineru-hyb+rot` standalone → `runs/dev-full/v15-*/reports`, LEDGER.md | 2026-09-22 | PENDING (Priority) |
| 33039 (upd) | drb-differ-v15 | — | DONE 17:44: v15-hyb **78.1** (text 85.3 RO 80.0 TEDS 69.2; +2.2 vs v13-pnt 75.9); verse-chunk (all) 77.7–78.0 (POETRY text −18: GT estrofes >300 chars não são re-fundidas); pipe lnum+eq 76.0 (POETRY 68.4→77.1); mineru-hyb+rot cru 68.5 | 2026-09-22 | DONE |
| 33046 | drb-differ-v16 | CPU 8c/48G/2h | variants_v16.txt: hyb + line-numbers + table-eq (+ --verse-chunk 1/150/300 só em blocos record-like, --verse-kind records) e pipe rec1 | 2026-09-22 | DONE: hyb-lnum-eq 78.1, rec1 78.2, rec150 78.2, **rec300 78.3** (text 85.6), pipe-rec1 76.0 |
| 33047 | drb-differ-test-zip differ-v15-hyb-20260922 | CPU | test-509: v13-pnt args sobre docling-v3+rot + mineru-hyb+rot → runs/evalai/differ-v15-hyb-20260922/submission/submission.zip | 2026-09-22 | DONE 21:07 valid 509, sha db577d6d… |
| 33239–33291 (outro PC, 25–26/09) | mineru-vlm (COMPLETED 37 min), matrix-v18 (norm 78.3, xy 77.9, pswap 77.1, all 76.6), puzzle, matrix-v19 (puzzle/dedup 78.3, bands 74.5, fuse04 78.2), test-zip differ-v19-puzzle-dedup-20260926 (valid 509, sha c8a494b1…) | — | vlm-adjud 33240/33259/33285 **FAILED** (vLLM/FlashInfer JIT: `ninja` não no PATH); 33286 matrix-v18 (vlmreg) nunca rodou (afterok) → cancelado | 2026-09-27 | — |
| 33356 | drb-vlm-adjud (relançado) | GPU 1 + 16c/128G/8h | vlm_adjudicate.sbatch com `PATH=$VENV/bin` (ninja) — Qwen2.5-VL-7B transcrição da fila (1673 crops já prontos) | 2026-09-27 | PENDING |
| 33357 | drb-matrix-v18 (relançado) | CPU 8c/48G/5h | afterok:33356 — v18-vlmreg/all com adjudicações VLM | 2026-09-27 | PENDING |
| 33356/33357 | — | — | 33356 FAILED em 1 min: ninja ok agora, mas FlashInfer JIT do sampler falhou "CUDA compiler and CUDA toolkit headers are incompatible" (nvcc pip 13.4.92 vs cuda_runtime 13.0.96); 33357 cancelado | 2026-09-27 | FAILED/CANCELLED |
| 33358 | drb-vlm-adjud (3ª tentativa) | GPU 1 + 16c/128G/8h | pin nvidia-cuda-nvcc/crt==13.0.*, VLLM_USE_FLASHINFER_SAMPLER=0, FLASHINFER_WORKSPACE_BASE em /raid | 2026-09-27 | PENDING |
| 33359 | drb-matrix-v18 | CPU 8c/48G/5h | afterok:33358 — v18-vlmreg/all | 2026-09-27 | PENDING |
| 33358/33359 | — | — | 33358 FAILED: engine subiu OK (nvcc pin funcionou), mas vLLM recusou `file://` crops: "Cannot load local files without --allowed-local-media-path"; fix em scripts/vlm_adjudicate.py (allowed_local_media_path=commonpath dos crops); 33359 cancelado | 2026-09-27 | FAILED/CANCELLED |
| 33360 | drb-vlm-adjud (4ª) | GPU 1 + 16c/128G/8h | idem 33358 + allowed_local_media_path | 2026-09-27 | PENDING |
| 33361 | drb-matrix-v18 | CPU 8c/48G/5h | afterok:33360 | 2026-09-27 | PENDING |
| 33360 | drb-vlm-adjud | GPU 1 | **COMPLETED** ~2 min: 1673 crops → 1252 decisões (pair-select 779, pair-replace 191, uni-replace 231, drops 51) em runs/dev-full/adjudication-queue-v2/adjudications.jsonl | 2026-09-27 | COMPLETED |
| 33361 | drb-matrix-v18 | CPU | rodou mas differ falhou "unrecognized arguments --norm-text/--order/--adjudications": scripts/tree_differ_v2.py e cópia do repo tinham sido sobrescritos às 11:00 (27/09) com versão pré-v18 (be86468). Só pswap/all/all-nc (sem VLM) avaliados = repetição. Restaurado do HEAD 8216ac9 | 2026-09-27 | COMPLETED (inútil) |
| 33362 | drb-matrix-v18 VLM_ONLY=1 | CPU 8c/48G/5h | v18-vlmreg + v18-all + v18-all-nc (com adjudicações VLM); norm/xy/pswap pulados | 2026-09-27 | PENDING |
| 33365 | drb-differ-v20 | CPU (differ_variants) | adjudicações VLM filtradas: notab / tight / sel vs 78.3 | 2026-09-27 | PENDING |
| 33365 | drb-differ-v20 | CPU | **notab 78.4, tight 78.5, sel 78.5** (text 85.6→86.1, TEDS 69.1 mantido) vs 78.3 — novo melhor dev | 2026-09-27 | COMPLETED |
| 33366 | drb-vlm-adjud-test | GPU 1 | fila+crops+VLM no split de teste (docling-v3+rot × mineru-hyb+rot, 509 págs) → runs/evalai/adjudication-queue/adjudications{,-sel,-tight,-notab}.jsonl | 2026-09-27 | PENDING |
| 33367 | drb-zip-v20-sel | CPU | afterok:33366 — zip differ-v20-vlmsel-20260927 (v16-rec300 args + --adjudications sel) | 2026-09-27 | PENDING |
| 33370 | drb-vlm3-zip Qwen3-VL-8B | GPU 1 + 16c/128G/6h | test-509 VLM adjudicate (reuse crops) → filter sel → zip differ-v21-qwen3vl8b-20260927 | 2026-09-27 | PENDING |
| 33371 | drb-vlm32-zip Qwen3-VL-32B-FP8 | GPU 1 afterany:33370 | best single-H100 VLM → zip differ-v21-qwen3vl32b-fp8-20260927 | 2026-09-27 | PENDING |
| 33372 | drb-vlm32bf16-zip Qwen3-VL-32B BF16 | GPU 2 (TP=2) afterany:33371 | best non-quantized on H100 → zip differ-v21-qwen3vl32b-bf16-20260927 | 2026-09-27 | PENDING |
| 34135 | srun drb-qfull | CPU 4c/16G | fila completa (--queue-sim 1.01: inclui pares "agreed") + crops: dev 5389, test 3659 → runs/{dev-full,evalai}/adjq-q32full | 2026-10-08 | DONE |
| 34137 | drb-vlm32-full (vlm_full.sbatch) | GPU 1 | v23: Qwen3-VL-32B-FP8 (VLLM_USE_DEEP_GEMM=0 + --enforce-eager, fix 33371) sobre a fila completa dev+test → adjudications{,-notab,-tight,-sel} | 2026-10-08 | PENDING |
| 34138 | drb-differ-variants v23 | CPU afterok:34137 | variants_v23.txt (v23-q32-{raw,notab,tight,sel}) dev-986 md2md | 2026-10-08 | PENDING |
| 34137/34138 | — | — | cancelados: substituídos pelo v24 (34161), que cobre a mesma fila de texto + tabelas + ordem | 2026-10-08 | CANCELLED |
| 34161 | drb-adjmax-v24 (adj_max.sbatch) | GPU 1 (h100n3,b200n1,h100n2) 16c/128G/10h | v24 adjudicador máximo, Qwen3-VL-32B-FP8 (fallback BF16): B tabelas (vlm_tables medoide TEDS), A texto (--skip-kinds table), C ordem (vlm_order caixas numeradas), dev+test → runs/{dev-full,evalai}/adjq-v24; depois zips test differ-v24-{T,Tg,Asel,Atight,AT,ATg,Osel,Ovlm,ATOs,ATOv}-20261008 + eval dev variants_v24.txt | 2026-10-08 | PENDING |
| 34161 | — | — | FAILED 0 s em dgx-H100-03 (sem log, sinal 53; 34045 falhou igual nesse nó) → ressubmetido como 34169 em b200n1,h100n2 | 2026-10-08 | FAILED |
| 34251 | drb-adjmax-h3 (adj_max_h3.sbatch, staging em /home/user_marcospaulo/v24stage) | GPU 1 h100n3 | v24 só estágios VLM | 2026-10-09 | CANCELLED (pedido do usuário, nunca iniciou) |
| 34169/34078/34132 | — | — | cancelados a pedido do usuário: nenhum job nas H100 por enquanto | 2026-10-09 | CANCELLED |
| 34364 | drb-adjmax-home (adj_max_h3.sbatch, roda de /home/user_marcospaulo/v24stage) | GPU 1 h100n2/h100n3/b200n1 | v24 estágios VLM test→dev (B gen, A raw, C ordem) com preflight + gpu_audit --kill; pós (TEDS/filter/zips/dev eval) no dgx-H100-02 | 2026-10-09 | COMPLETED 51 min, GPU 4 apenas, gpu_audit 0 violações; saídas copiadas p/ /raid, /home/v24stage apagado |
