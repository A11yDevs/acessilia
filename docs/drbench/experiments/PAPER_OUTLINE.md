# Outline — system paper (long, ACL/EMNLP format) — DocInsights 2026 Shared Task, Dr.DocBench track

Deadline: 2026-09-15 23:59 UTC (OpenReview EMNLP/2026/Workshop/DocInsights_Shared_Task). Organizers ask for: system, data, models, prompts, tools, evaluation choices, lessons learned.

**Framing rule:** the paper is about the Dr.DocBench problem and our architecture. "Acessilia" is only the system name — do NOT frame the work around accessibility.

## Working title
*Acessilia at Dr.DocBench 2026: A Generalist–Specialist Adjudication Architecture for Structurally Faithful Page Parsing*

## Thesis
A Dr.DocBench page is heterogeneous (text, tables, formulas, chemistry, music, multi-column, noisy scans) and no single parser dominates on every component (leaderboard: GPT-5.5 61.94, MinerU 2.5 54.37, PaddleOCR 34.78; our pilot: Docling better on average, MinerU wins on 4/10 pages). Structurally faithful parsing is therefore best organised as: **generalists localise → restricted routing → domain specialists emit the formal language of the object → adjudication over a canonical tree**.

## Contributions (state clearly what is implemented vs designed)
1. Generalist–specialist architecture with a canonical document tree and a Toolbox *capability* layer decoupled from concrete tools.
2. Controlled Docling vs MinerU comparison under Dr.DocBench metrics on a stratified dev subset, per component and per layout / special_issue stratum.
3. Complementarity analysis: per-page oracle selection (upper bound for an adjudicator) and inter-tree agreement as a confidence signal — empirical motivation for the adjudicator.
4. Lessons on the output contract (`\[ \]`, `<table>` with spans, `\ce{}`, `smiles`/`musicxml` fences) and on local vs official evaluation.

## Sections (target ~8 pages of content)
| # | Section | Content | Source of numbers |
|---|---|---|---|
| 0 | Abstract | problem, architecture, headline dev result per provider + oracle gain, central lesson | runs/dev/summary.md |
| 1 | Introduction (~1 p.) | heterogeneity; why neither one VLM nor one pipeline suffices; thesis; contributions | — |
| 2 | Related Work (~0.6 p.) | benchmarks (OmniDocBench, Dr.DocBench); pipelines (MinerU, Docling, PaddleOCR, Marker); end-to-end (Nougat, GOT-OCR2, olmOCR, dots.ocr, MonkeyOCR); specialists (UniMERNet, TableFormer, MolScribe, RxnScribe, DECIMER, homr, Audiveris); OCR combination (ROVER) | references.bib |
| 3 | Task and Data (~0.6 p.) | page unit; Markdown contract (HTML tables w/ rowspan/colspan, `\( \)` / `\[ \]`, `\ce{}`, ```smiles, ```musicxml, figures ignored); metrics (Edit↓, TEDS↑, CDM↑, Reading Order↑; Overall = per-page mean of available components); dev 986 pages / 66 docs vs test 509 / 34 docs / 28 BISAC subjects; submission rules (3/day, 2 selectable) | HF dataset card, evaluator-specification.html |
| 4 | System (~2.5 p.) | 4.1 overview (Fig. 1); 4.2 Toolbox: `document.structure.extract`, capabilities `recognize-{math,table,chemical-structure,music}`; 4.3 canonical tree (schema, `content_status`); 4.4 generalist layer (Docling, MinerU: layout/OCR/table/formula, configs); 4.5 Tree Differ + VisualAdjudicator (bbox/text alignment, closed 10-class taxonomy: plain_text, table, math_formula, chemical_formula, chemical_structure, chemical_reaction, music_score, figure, code, unknown; VLM only routes; confidence < 0.75 → run two specialists); 4.6 specialist families (Table 1: object → tools → representation → target metric); 4.7 serialisation `canonical_to_drbench_md`; 4.8 submission builder + strict validator. **Mark 4.5–4.6 as designed; 4.2–4.4, 4.7–4.8 as implemented.** | repos/acessilia PR #97, repos/acessilia-toolbox develop |
| 5 | Experimental Setup (~0.6 p.) | stratified dev subset (N per stratum: table, display formula, multi-column, fuzzy_scan/colorful, plain); tool versions; hardware (Slurm cluster, CPU/GPU); local metrics vs official evaluator; whether CDM was computed | runs/dev/subset.json, runs/dev/*/reports |
| 6 | Results (~1 p.) | T2 overall + components × provider (N per component); T3 by layout and special_issue; T4 per-page oracle vs best single provider; EvalAI leaderboard if available | runs/dev/summary.md, runs/SUBMISSIONS.md |
| 7 | Analysis (~1 p.) | typical errors with examples: headings undetected (both), MinerU drops captions/page numbers, formula delimiters, tables with spans, reading order in multi-column; agreement ↔ error correlation (motivates Differ) | eval drilldown |
| 8 | Lessons Learned (~0.5 p.) | output contract is worth points; approximate local metrics mislead (TEDS/CDM); page unit loses document context; CPU vs GPU cost; strict zip validation | — |
| 9 | Conclusion & Future Work (~0.3 p.) | implement adjudicator + specialists; local VLM router; iterate submissions until Oct 10 | — |
| — | Limitations · Ethics (short: public data, compute) · References · Appendix: canonical JSON schema, serialisation rules, router prompt (design), subset list, Slurm configs | — |

## Figures / tables
- Fig. 1 architecture (TikZ): generalists → canonicalisation → Tree Differ → VisualAdjudicator → specialist families → domain adjudicators → canonical tree → Markdown.
- Fig. 2 one page: Docling vs MinerU vs GT excerpt.
- Fig. 3 histogram of per-page overall difference (Docling − MinerU) on the dev subset.
- Table 1 specialist families. Table 2 main results. Table 3 by stratum. Table 4 oracle.

## Specialist families (Table 1)
| Object | Tools (generalist + specialists) | Output | Metric |
|---|---|---|---|
| Text / structure | Docling, MinerU | Markdown | Edit distance, Reading order |
| Math formula | MinerU, Docling (CodeFormula), UniMERNet | LaTeX `\( \)` / `\[ \]` | CDM |
| Table | MinerU, Docling/TableFormer, Docling/Granite Vision | HTML with spans | TEDS |
| Chemical formula / equation | VLM → mhchem | `\ce{...}` | (text) |
| Chemical structure | MolSight, MolScribe, DECIMER | ```smiles | (text) |
| Reaction scheme | RxnScribe, OpenChemIE | semantic JSON → `\ce{}` / smiles | (text) |
| Music score | homr, Audiveris | ```musicxml (no `<?xml?>`, no `<score-partwise>`) | OMR (exploratory) |

## Contingency
If the dev-subset evaluation is not ready by ~21:00 UTC, the paper stands on: full architecture + pilot results (10 dev pages, PR #97: Docling 81.15 / MinerU 77.84 overall; text_ed 80.89 / 77.58; reading_order 81.42 / 78.11; MinerU better on p33, p37, p38, p39; worse on p34 (−16.1), p41 (−15.2); p35 both 0) + per-page oracle on those pages, and states the larger subset as ongoing.
