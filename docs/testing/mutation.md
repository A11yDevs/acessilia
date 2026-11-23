# Mutation testing and test subsumption

> A Brazilian Portuguese translation is available in
> [mutation.pt-br.md](mutation.pt-br.md).

This is PR 3 of [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
a bounded mutation experiment on two small docstruct modules, the test
subsumption relations it exposes, and the cost/benefit of the approach. It does
not change production code or the CI gate.

- **Snapshot:** `develop` at `cd7003d2` (2026-11-23), Python 3.12.13.
- **Tool:** [`scripts/tests/mutation_report.py`](../../scripts/tests/mutation_report.py).
- **Modules:** `docstruct.fusion.flood` and `docstruct.text.equations`.
- **Reports:** [`mutation-flood.json`](mutation-flood.json),
  [`mutation-equations.json`](mutation-equations.json).
- **Coverage comparisons:** [`overlap-flood.json`](overlap-flood.json),
  [`overlap-equations.json`](overlap-equations.json).

## Why a bounded experiment instead of a new gate

Mutation testing runs the tests once per artificial defect. A full run of the
Acessilia suite would multiply a 5-minute suite by hundreds or thousands of
mutants, which is unacceptable as a pull-request gate. The experiment therefore
answers a narrower question first:

> Do tests with near-identical coverage actually detect different defects, and
> can we see a subsumption relation that coverage alone does not show?

Two small deterministic docstruct modules were selected, each with a focused
test file. The harness mutates the module with AST operators, copies the
docstruct package into a temporary directory, runs the focused tests against
each mutant with `PYTHONPATH` pointing at the copy, and records which tests
failed.

### Tools considered

| Option | Why it was not adopted first |
|---|---|
| `mutmut` | Adds a dependency and a stateful working copy; configuration for the `src/` layout and per-run selection would have to be tuned before the first result. Remains the natural candidate for a periodic, larger run. |
| `cosmic-ray` | More operators and distributed execution, but a heavier operational model than the question needs. |
| This harness | No new dependency, deterministic mutations, one module at a time, the test-to-mutant matrix in the report. Fewer operators than the mature tools and no automatic equivalent-mutant detection. |

The harness is a proof of concept, not a replacement for a mature tool. Its
value is that the experiment is reproducible in this repository today and can
be repeated in a scheduled job.

## Method

```bash
# Generate and inspect the mutations without running them
uv run --extra dev python scripts/tests/mutation_report.py \
  --module libs/docstruct/src/docstruct/fusion/flood.py \
  --tests tests/test_flood.py --suite libs/docstruct \
  --source-root libs/docstruct/src --list-mutants

# Run the experiment with line coverage classification and overlap comparison
make test-mutation

# The equations experiment
uv run --extra dev python scripts/tests/mutation_report.py \
  --module libs/docstruct/src/docstruct/text/equations.py \
  --tests tests/test_equation_numbers.py --suite libs/docstruct \
  --source-root libs/docstruct/src \
  --coverage-file var/coverage/docstruct/.coverage \
  --overlap docs/testing/overlap-equations.json \
  --output var/mutation/equations.json
```

Operators: comparison swaps (`==`/`!=`, `<`/`<=`, `>`/`>=`, `in`/`not in`,
`is`/`is not`), boolean `and`/`or`, boolean constant flips, `not` removal,
condition negation and `+=`/`-=`. A mutant that makes the tests fail is
**killed**; a mutant that leaves them passing is **surviving**. A surviving
mutant on a line the suite never executes is reported as **uncovered**, not as
a test weakness. Timeouts and invalid runs are reported separately. A timeout sits in the mutation-score
denominator but not in the numerator: a hang is a separate outcome, not a kill.

The mutation score is `killed / (killed + survived + timeout)` over covered
mutants. Equivalent mutants are **not** identified automatically: a surviving
mutant needs manual judgement.

## Results

| Module | Mutants | Killed | Survived | Timeout | Uncovered | Invalid | Mutation score |
|---|---:|---:|---:|---:|---:|---:|---:|
| `docstruct.fusion.flood` | 17 | 14 | 3 | 0 | 0 | 0 | 82.3% |
| `docstruct.text.equations` | 28 | 28 | 0 | 0 | 0 | 0 | 100% |

The two experiments took about 15 and 26 seconds respectively, including the
per-mutant interpreter start. That is affordable for two modules, not for the
whole suite on every pull request.

### Surviving mutants in `flood_guard`

| Mutant | Line | Change | Why it survives |
|---|---:|---|---|
| M005 | 50 | `na < min_blocks` → `na <= min_blocks` | No test uses exactly `min_blocks` blocks. |
| M011 | 57 | `len(text) <= short` → `len(text) < short` | No test uses a block with exactly `short` characters. |
| M016 | 63 | `len(keep) < len(a)` → `len(keep) <= len(a)` | No test triggers the guard without dropping a block. |

These are real boundary gaps, not equivalent mutants. The test file covers
10 and 40 blocks and text lengths `2` and `40`, but not the exact thresholds
30, 15 and the "triggered but kept everything" path. PR 4 can add three
boundary tests and re-run the same experiment; the expected result is 17/17.

### Subsumption

A test A subsumes B when every mutant B kills, A also kills. This is a
mutation-based relation, stricter than coverage similarity.

For `flood_guard`, the strongest relation is
`test_descarta_blocos_curtos_sem_palavra_do_lexico`: it kills the seven mutants
that `test_blocos_longos_sao_preservados`,
`test_blocos_nao_textuais_sao_preservados`,
`test_lexico_vazio_descarta_todos_os_curtos` and
`test_tag_entra_nas_stats` also kill, and it kills four additional mutants
(7 shared + 4 exclusive = 11 in its kill set).
`test_blocos_longos_sao_preservados` and
`test_blocos_nao_textuais_sao_preservados` have **equal** kill sets.

Those pairs have coverage Jaccard 1.0, so coverage overlap and subsumption
agree here. The conclusion is still not "remove the smaller tests": they assert
different keep/drop behaviour and different `stats` keys, and the mutation
matrix only says which artificial defects each detects.

For `equations`, the complete relation set has **410 directed subsumption
pairs**; the report records the first 50 as examples. Some pairs have no
high-similarity coverage pair at all: for example, tests that
assert different export boundaries are mutation-subsumed without covering the
same narrow line set. That is the important complement: **coverage overlap is
not a substitute for mutation detection**, and mutation subsumption without a
contract review is not a licence to remove a test.

### Mutants detected by exactly one test

| Module | Test | Mutants |
|---|---|---|
| `flood` | `test_descarta_blocos_curtos_sem_palavra_do_lexico` | M007, M013, M015, M017 |
| `flood` | `test_ratio_e_respeitado` | M006 |
| `equations` | `test_existing_number_and_idempotence` | M013 |

These are the opposite of redundancy: the test is the only detector of a
specific mutation and must stay even if its coverage looks duplicated.

## Answers to the PR 3 questions

| Question from #644 | Result |
|---|---|
| Evaluate Python mutation tools | `mutmut` and `cosmic-ray` assessed; the bounded harness was chosen for the first experiment and the mature tools remain candidates for periodic runs |
| Select small deterministic docstruct modules | `fusion/flood.py` and `text/equations.py` |
| Run mutations in a limited scope | 17 and 28 mutants, two focused test files, under 30 seconds each |
| Record which tests detect each mutation | Per-mutant `killers` list in both reports |
| Build experimental subsumption relations | `subsumption` section, including equal kill sets |
| Identify surviving mutants | 3 in `flood`, 0 in `equations` |
| Compare with coverage overlap | Jaccard added per subsumption pair; the relation agrees in `flood` and diverges in `equations` |
| Feasibility for SDK and core | The harness is language-level and component-agnostic; the cost of broader runs is the open question, not the mechanics |

## Cost and next steps

- **Do not add mutation testing to every PR.** The per-mutant interpreter start
  dominates and the whole suite would multiply it.
- **Run selected modules periodically.** A scheduled job can run the same
  command for a small list of deterministic modules and publish the reports.
- **Act on surviving mutants.** The three `flood` boundaries are the
  validation target for PR 4: add the tests, rerun, and compare the score
  before and after.
- **Do not treat subsumption as deletion evidence.** A subsumed test can still
  be the only one documenting a contract, a localized message or a failure
  mode; the mutation operator set is also incomplete.

The full docstruct overlap report is
[`overlap-docstruct.json`](overlap-docstruct.json). It is not used as the
mutation comparison input for the two small modules; it is the broader picture
of the library suite.

## Limitations

- **Limited operator set.** The harness targets conditions and simple
  operators, not complex API substitutions, argument removal or return-value
  changes.
- **No equivalent-mutant detection.** A surviving mutant is a question, not a
  verdict.
- **One module and its focused test file per run.** Cross-module integration
  defects are outside this experiment.
- **AST unparse changes formatting.** The mutated copy is compiled and executed
  but is not the original text; comments and formatting are not preserved.
- **Coverage classification comes from a separate run.** If the coverage file
  is stale, an uncovered mutant can be misclassified.
- **The subsumption example limit.** `--max-subsumption` (default 50) caps both
  the Markdown table and the JSON list. `summary.subsumption_total` records the
  complete relation count; the `equations` run has 410.
