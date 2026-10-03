# Frozen paired replay

Freeze two committed versions before comparing their adapters and fusion against
the official Dr.DocBench evaluator. This uses existing raw inference JSON; it
does not run OCR again. Keep specifications, datasets, source exports and results
outside the Acessília and Toolbox repositories.

Create a local JSON specification with paths relative to the specification file
(absolute paths are also accepted):

```json
{
  "data_root": "../reading-order-evaluation",
  "pages": "../reading-order-evaluation/data/pages.json",
  "dataset": {"revision": "DATASET_COMMIT", "split": "dev"},
  "seed": 20261003,
  "inference": {"identity_source": "describe how model versions were obtained"},
  "evaluator": {"repo": "EVALUATOR_REPO", "ref": "EVALUATOR_COMMIT"},
  "variants": {
    "baseline": {
      "acessilia": {"repo": "ACESSILIA_REPO", "ref": "BASELINE_COMMIT"},
      "toolbox": {"repo": "TOOLBOX_REPO", "ref": "BASELINE_TOOLBOX_COMMIT"},
      "policy": "v12", "fusion_args": []
    },
    "candidate": {
      "acessilia": {"repo": "ACESSILIA_REPO", "ref": "CANDIDATE_COMMIT"},
      "toolbox": {"repo": "TOOLBOX_REPO", "ref": "CANDIDATE_TOOLBOX_COMMIT"},
      "policy": "v12", "fusion_args": []
    }
  },
  "evidence_files": []
}
```

Each selected page requires `id`, `subject`, `document_id`, `page`, `batch` and
`image`, as in the existing local selection. `data_root` contains
`raw/{docling,mineru}/<id>.json`, `data/hf/<image>` and per-page ground truth at
`data/hf/dev/<subject>/<document_id>/mds/<document_id>_<page>.md`.
This first runner supports the dev split with per-page Markdown references.
An optional `language` on a selected page overrides the historical `en` default.

```bash
python -m scripts.drbench.experiments.eval.frozen_inputs \
  --spec /external/experiment/spec.json --out /external/experiment/e00
```

The output directory must be new. The manifest records the resolved commits and
archive hashes, selected inputs and SHA-256 hashes, and configuration evidence.
Source exports use `git archive`: dirty and untracked files are excluded. Commit
a candidate before freezing it; otherwise its edits are not evaluated.

Model identity in `inference` is supplied evidence, not an automatic assertion
that those model weights were loaded. Preserve extraction logs, options and locks
through `evidence_files`; new inference should additionally record actual weights.

## Replay, fusion and official evaluation

Use the environment already installed for the evaluator, plus the lightweight
Toolbox/normalization dependencies. Sources are imported from the frozen exports;
heavy OCR packages are unnecessary for replay.

```bash
python -m scripts.drbench.experiments.eval.frozen_replay \
  --spec /external/experiment/spec.json --out /external/experiment/e01 \
  --require-zero-regressions

# Or evaluate an existing, not-yet-executed frozen export:
python -m scripts.drbench.experiments.eval.frozen_replay \
  --frozen /external/experiment/e00
```

`--limit N` selects a pilot before freezing. It always requires a new output
directory, so a pilot cannot consume old predictions. A completed or failed run
is never reused; create another run to retry. Failed runs retain their logs and
failure status. No source checkout or old result directory is cleaned.

The manifest records commands, resolved CLI arguments captured during execution of each frozen version,
resolved policy (including the CLI garbage fallback override), package versions,
timings, runner hashes and source hashes. The backend's generated translation
catalogues are recorded separately; mutation of committed source is rejected.

Outputs include provider payloads, `.blocks.json`, fusion Markdown, `decisions.csv`,
official matched samples, `per-page.csv`, `summary.json` and `REPORT.md`. Tables
(TEDS and edit distance) and formula edit distance accompany RO and text; CDM and
Overall are outside this runner. TEDS is summarized per page from official samples.

The quality gate rejects per-page losses and asymmetric metric coverage, even
when the mean improves. Missing required evaluator outputs fail the run. An
empty official sample list is recorded as missing, not as a perfect score; zero
paired RO/text scores are inconclusive. Without `--require-zero-regressions`, a
successful measurement may finish with a rejected quality gate. With it, rejection
or inconclusive coverage returns a nonzero exit after preserving the report.

Passing this metric gate still requires content counterexamples and external
validation before accepting a behavior change. The official matcher can omit
tables absent from both outputs; this runner does not claim to prove preservation
of such tables.

For a first validation, use identical commits/settings for both variants. Then
reproduce the historical comparison. For an ablation, change one source revision
or one configuration while holding everything else fixed. `fusion_args` accepts
the frozen CLI's options but cannot override paths or the recorded preset.

For a unilateral-deduplication ablation, set the candidate's `fusion_args` to
`["--no-unilateral-dedup"]` and leave baseline arguments empty, using the same
committed version for both. This disables only that deletion rule; matching,
swallowing guards, content selection and fallback stay enabled. The current rule
requires the full normalized content in a selected emitted text block and at
least 0.6 containment of the candidate box in that emitted block's box. Missing
coordinates do not justify deletion; numeric punctuation is preserved.

For a Docling native-order ablation, add `"docling_native_order": true` to the
candidate variant and leave the baseline setting absent or false. This passes
`native_order=True` to the frozen Toolbox adapter; use a revision supporting that
keyword. False leaves constructor defaults unchanged, preserving replay of older
adapters. The manifest records the boolean and extraction configuration records
the actual adapter options. The current adapter defaults to collection order;
native traversal is experimental and disabled by default.

Evaluate provider Markdown separately from fusion Markdown when assessing an
adapter change. Neutral fusion scores can conceal a provider conversion loss.

Native MinerU indices are transported without changing iteration or fusion
order by default. The adapter stores provider, source, page index and native block
index in `metadata.reading_order_context`. `provider_blocks`, the persisted
block loader and both library/CLI conversions retain that context. `DiffBlock`
stores the contributing contexts in `order_sources`; block joins concatenate
them instead of claiming one native index for the joined block. Figures and
empty Markdown still follow the existing loader filters. Legacy blocks without
context have no order sources. This transport step requires identical provider
and fusion Markdown before experimenting with consuming those indices.

For that separate experiment, set `"mineru_native_order": true` on the candidate
variant, using a Toolbox revision supporting `native_order=True`. Leave Docling
mode and all fusion settings fixed. MinerU sorts each page only with complete,
valid, distinct indices; missing/invalid values or ties retain the received
sequence and record the reason. The flag is frozen and actual constructor
options are recorded in extraction configuration. Default and false settings
pass no constructor override, preserving the selected historical source's
defaults. A storage shuffle is a metamorphic test; restoring the original
Markdown does not count as a gain on naturally occurring benchmark pages.

All source `provenance` records now survive provider elements, persisted blocks,
CLI/library conversion and backend canonical conversion. `DiffBlock.provenance`
contains the contributing records; paragraph and line joins concatenate them,
including repeated records. Copies preserve source payloads. Existing picture
and empty-Markdown filters still apply. Legacy inputs without provenance have
an empty collection; no coordinates or character spans are inferred.

These records retain source page numbers, coordinate units/origins and original
character offsets. They do not describe spans in transformed Markdown. Keeping
them is a transport change: the replay still uses its previous first-provenance
active box and page assignment, without unions or additional blocks. Validate
unchanged Markdown, active geometry and all retained records before consuming
this evidence in matching or segmentation.

The backend has a separate geometry limitation: its canonical conversion reads
flat `bbox`/`page_size`/`coord_origin` fields, while current provider manifests
store geometry in provenance and document pages. Its grouping also reads the
legacy `page` field. Carrying provenance does not fix this mapping. A separate
backend contract and behavioral experiment must cover active boxes and page
assignment before relying on geometry for production matching.
