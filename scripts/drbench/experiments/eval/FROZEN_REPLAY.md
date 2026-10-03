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
