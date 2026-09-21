# Slurm jobs — Dr.DocBench (partição h100n2, nó dgx-H100-02)

Todos os jobs fazem `source runs/slurm/env.sh` (caches em `/raid/user_marcospaulo/cache`). Logs em `runs/slurm/logs/<name>_<jobid>.log` (+ `_docling.log` / `_mineru.log` / `_toolbox.log` para os serviços). Scripts: `setup.sbatch`, `pipeline.sbatch` (genérico, reentrante), `full_gpu.sbatch`.

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
cd /raid/user_marcospaulo/drdocbench
sbatch -c 32 --mem 128G --time 06:00:00 --job-name drb-dev-docling \
  --export=ALL,PROVIDER=docling,IMAGES_ROOT=$PWD/runs/dev/subset-images,OUT_DIR=$PWD/runs/dev/docling/predictions,SAMPLE=0 \
  runs/slurm/pipeline.sbatch
# ITEMS_FILE=<lista de ids> opcional; SAMPLE=N limita; reentrante (pula <id>.drbench.md existentes)
```

## Bugs / workarounds
- **acessilia-toolbox** `src/acessilia_toolbox/core/normalization/builder.py:188` chama `document.iterate_items(...)` e `:460` `document.pages.items()`, mas `src/acessilia_toolbox/providers/mineru_document.py::MineruDocument` não implementa `iterate_items` e `pages` retorna `list` → HTTP 500 em `document.structure.extract` com provider mineru. Workaround sem tocar no repo: `scripts/toolbox_shim/sitecustomize.py` carregado via `PYTHONPATH` só no processo uvicorn da toolbox (ver `pipeline.sbatch`). Mapeia blocos MinerU → labels Docling (`text/section_header/table/formula/...`), page_no 1-based, tabela como HTML, fórmula como `$$…$$`.
- **Docling models** foram baixados para `~/.cache/docling/models` pelo `docling-tools models download`; movidos para `/raid/user_marcospaulo/cache/docling/models` (symlink na home) e `DOCLING_ARTIFACTS_PATH` em `env.sh`.
- **mineru.json** gerado em `~/mineru.json` com `models-dir.pipeline` apontando para o HF cache em `/raid`; cópia em `/raid/user_marcospaulo/cache/mineru/mineru.json` (`MINERU_TOOLS_CONFIG_JSON`). Pipeline usa `MINERU_MODEL_SOURCE=local`.
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
| 32626 | drb-setup-cdm | h100n2 -c8 32G 3h | `runs/slurm/setup_cdm.sbatch`: node portátil + TeX Live 2025 scheme-small (xelatex, xeCJK) + magick shim + Source Han Sans em /raid/user_marcospaulo/opt → `runs/slurm/cdm_env.sh`; habilita CDM local (`end2end_full.yaml`) | 2026-09-16 |
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
| 32745 | drb-differ-v4 | CPU 8c/48G 2h | S6.1: tree_differ_v2 variantes v4-decor (decor tail), v4-decor-junk, v4-pick (text-pick auto), v4-merge (+merge-paragraphs), v4-merge-dpick (merge, pick docling) em dev-986 md2md (`runs/dev-full/variants_v4.txt`, CDM=0) → runs/dev-full/v4-* + LEDGER | 2026-09-18 |
| 32746, 32747 | srun drb-orient-test / drb-orient-venv | CPU 4c/16G | teste de `scripts/orient_pages.py` (RapidOCR) em 4 págs; venv `repos/.venv-orient` (rapidocr+onnxruntime+opencv) — 2/2 páginas rotate270 detectadas (score270/score90 ≈ 14×) | 2026-09-18 13:18 UTC |
| 32748 | drb-orient | CPU 16c/48G 3h | `runs/slurm/orient.sbatch`: orientação de dev-986 + test-509 → runs/orientation_{dev,test}.json + cópias giradas em data/rotated/{dev,test} (items.txt) | 2026-09-18 13:22 UTC |
| 32749→32750 (32749 cancelado: backend inválido) | drb-mineru-vlm | GPU 1×H100 16c/128G 10h (PENDENTE, fila cheia) | Alavanca E: MinerU 3.4.5 backend `hybrid-engine` (VLM MinerU2.5 + pipeline), TAG mineru-hybrid (MinerU2.5 1.2B, HF) via `runs/slurm/mineru_vlm.sbatch` + `providers-config-vlm.yaml`; estágios dev-120 → dev-986 → test-509 → runs/{dev,dev-full,evalai}/mineru-vlm/predictions (--save-raw) | 2026-09-18 13:35 UTC |
| 32745 DONE | drb-differ-v4 | | **v4-decor 72.8 · v4-decor-junk 72.8 · v4-pick 73.3 · v4-merge 73.7 (text 81.3 RO 77.3) · v4-merge-dpick 73.2** vs v3a-clean 66.8 (evalai_style md2md w1) | 13:40 UTC |
| 32751 | drb-test-zip differ-v4-merge-20260918 | CPU 8c/32G 1h | `runs/slurm/differ_test_zip.sbatch`: tree_differ_v2 v4-merge sobre test-509 docling-v3 + mineru-v3 → runs/evalai/differ-v4-merge-20260918/{predictions,submission/submission.zip} + validate | 2026-09-18 13:42 UTC |
| 32752 | drb-differ-v5 | CPU 8c/48G 2h | afinação sobre v4-merge: tau 0.7/0.5, lam 0.3/0.7, garbage-fallback 0.25, merge-frac 0.5 (`runs/dev-full/variants_v5.txt`) | 2026-09-18 13:42 UTC |

## 2026-09-18 (tarde)
- 32751 drb-test-zip DONE: runs/evalai/differ-v4-merge-20260918/submission/submission.zip valid 509 pages sha256 79e69874a4ab533cafa64f5e4b8ef55bfd02651be80b5856a35cee94b0a38d88
- 32748 drb-orient DONE: dev 46/986 rotadas (data/rotated/dev), test 16/509 (data/rotated/test); runs/orientation_{dev,test}.json
- 32753 drb-differ-v6 (CPU 8c/48G 2h): variants_v6.txt — lever K --suppress-regions (+ --merge-min-sim) sobre v4-merge
- 32754 drb-rot-infer SPLIT=dev (CPU 16c/96G 6h): docling+mineru nas 46 páginas rotacionadas -> runs/dev-full/{docling,mineru}-rot
- 32755 drb-rot-infer SPLIT=test (afterany:32754): 16 páginas -> runs/evalai/{docling,mineru}-rot
- 32756 drb-differ-v7 (CPU 8c/48G 2h): variants_v7.txt — lever L --fuse-lines (index/reference columns) sobre v6-sup-msim
- 32757 drb-differ-v8 (CPU 8c/48G 2h): variants_v8.txt — --pick-guard (Docling swallowed columns) + --merge-side sobre v7-fuse
- 32756/32757 CANCELADOS (consolidados em v9)
- 32758 drb-differ-v9 (CPU 8c/48G 2h): variants_v9.txt — fuse-lines, pick-guard, decor-wins, running-heads (6 variantes)
- 32758 CANCELADO (v9 redefinido) → 32759 drb-differ-v9 (8 variantes: supT/supQ/fuse/guard/decor-wins/running-heads)
- 32759 DONE (11 min): v9 → melhor v9-supQ-fg-dw evalai_style=74.6 (text 84.5, RO 76.9); running-heads regride RO (75.9)
- 32760 drb-differ-v10 (CPU 8c/48G 2h): variants_v10.txt sobre overlays docling+rot / mineru+rot (46 páginas rotacionadas re-inferidas)
- 32754/32755 DONE: rot-infer dev 46/46 e test 16/16 (docling+mineru); overlays em runs/dev-full/{docling,mineru}+rot e runs/evalai/{docling,mineru}-v3+rot
- 32760 DONE (12 min): v10 rot → v10-rot-best 75.5 (text 85.0 RO 78.1 TEDS 63.3); rotação +0.9
- 32761 drb-differ-v11 (CPU 8c/48G 2h): variants_v11.txt sobre +rot — fuse-h-ratio 0.6, fuse-max-len 300, table-probe
- 32762 drb-zip-v10rot (CPU): zip de teste differ-v10-rot-best-20260918 (docling-v3+rot, mineru-v3+rot; args v10-rot-best)
- 32762 DONE: zip differ-v10-rot-best-20260918 valid 509, sha e5974a6b…
- 32761 DONE (~17 min): v11 → v11-hr-cap300 75.7 (text 85.1 RO 78.7 TEDS 63.3); hr +0.1, cap300 +0.1, table-probe neutro/−0.1 text, lam03 = lam05
- 32763 drb-differ-v12 (CPU 8c/48G 2h): variants_v12.txt sobre +rot — base v11-hr-cap300 + running-heads 3 / pagenum-cap 2|4 / table-full-page 0.85
- 32763 DONE (~15 min): v12 → rh3 75.7 (neutro) · pc2 75.9 (RO 79.2) · rh3-pc2 75.9 · rh3-pc2-tfp 75.9 · **rh3-pc4 75.9 (text 85.1 RO 79.3 TEDS 63.3)**; pagenum-cap +0.2
- 32764 drb-zip-v12 (CPU): zip de teste differ-v12-rh3-pc4-20260918 (docling-v3+rot, mineru-v3+rot; args v12-rh3-pc4)
- 32764 DONE: zip differ-v12-rh3-pc4-20260918 valid 509, sha 3caf5bdd…
- 32765 drb-differ-v13 (CPU 8c/48G 2h): variants_v13.txt sobre +rot — base v12-rh3-pc4 + flood-guard 5|3 / pic-need-text / formula-text (ciclo 3 M1-M3)
- 32765 DONE: v13-fg 75.8 (text 85.2 RO 79.0) | v13-pnt 75.9 (85.0/79.4) | v13-ft 75.9 | v13-all 75.9 (85.1/79.2) | v13-all-fg3 75.9 — todos neutros em dev; 48 flood-pages, 178 pic-suppress-skipped, 11 formula->text
- 32766 drb-zip-v13 (CPU): zip teste differ-v13-pnt-ft-20260918 = v12-rh3-pc4 + --pic-need-text --formula-text (flood-guard descartado: RO −0.3 em dev)
- 32766 DONE: zip differ-v13-pnt-ft-20260918 valid 509, sha da91e889…
