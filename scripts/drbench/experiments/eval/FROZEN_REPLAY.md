# Frozen paired replay

Freeze two committed versions before comparing their adapters and fusion against
the official Dr.DocBench evaluator. This uses existing raw inference JSON; it
does not run OCR again. Keep specifications, datasets, source exports and results
outside the Acessília and Toolbox repositories.

Create a local JSON specification with paths relative to the specification file
(absolute paths are also accepted):

```json
{
  "data_root": "../../../reading-order-evaluation",
  "pages": "../../../reading-order-evaluation/data/pages.json",
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

The manifest records commands, resolved CLI defaults from each frozen version,
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
