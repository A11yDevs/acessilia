# Presentation fixtures

Real presentation decks used by the suite and by the benchmarking scripts.

| File | Dataset id | Pages | What it covers |
|---|---|---|---|
| `grandezas-e-medidas-42pgs.pdf` | `006` | 42 | The full chemistry deck: a title slide, diagrams, tables, formulas, drawn molecules, and slides whose text is one picture |
| `grandezas-e-medidas-pg3-42.pdf` | `007` | 1 | The deck's page 3, with the SI units table |
| `grandezas-e-medidas-pg7-42.pdf` | `008` | 1 | The deck's page 7, with a bar chart |

The 42-slide deck is the case 006 from
[A11yDevs/acessilia-dataset](https://github.com/A11yDevs/acessilia-dataset):
its ground truth is `input/presentation-reference/ground_truth.csv` and its
expectations are `input/presentation-reference/expectations.json`, both on the
dataset's `main` branch. The copy here is byte-identical to the dataset's
`input/006.pdf` (SHA-256
`ce9874fd3219241766772904c84f7eed3e340befa9a6beee6ca206308b8a549f`);
`tests/test_slide_case_e2e.py` checks that when the dataset clone is present.

Do not edit these files in place: they are source documents, not generated
fixtures. A new case belongs in the dataset first, then in this directory only
when a suite needs a copy that runs without the clone. The scorecard and its
commands are documented in [docs/bench.md](../../../docs/bench.md#presentation-reference-case).
