# Test optimization results: cached field specs and boundary tests

> A Brazilian Portuguese translation is available in
> [optimizations.pt-br.md](optimizations.pt-br.md).

This is PR 4 of [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
the measured optimizations selected from the baseline and the mutation
experiment. It does not remove tests, change coverage thresholds or add a new
CI gate.

- **Snapshot:** `develop` at `7c9311f` (2026-11-23), Python 3.12.13.
- **Baseline:** the PR 1 method, one quiet run on the same reference machine.
- **Machine-readable after-baseline:** [`baseline-after.json`](baseline-after.json).
- **After the boundary tests:** [`mutation-flood-after.json`](mutation-flood-after.json).

## 1. Cache the field specifications used by document validation

### Problem

The baseline measured `docstruct` at 96.48 seconds of wall time, with
`test_long_parent_chains_are_acyclic` alone taking 23.59 seconds. Profiling that
test showed where the time went:

| Function | Cumulative time | Calls |
|---|---:|---:|
| `typing.get_type_hints` (through `field_specs`) | 3.53s of 4.9s under the profiler | 6,007 |
| `field_specs` | 2.76s | 4,004 |
| `structured_document_from_payload` | 1.52s | 1 |

`field_specs()` resolved the same type hints for every element and then rebuilt
the same constraint dictionaries. A 2,000-element document paid for the same
introspection 2,000 times. This is production work, not a test fixture: the
same path validates real manifests.

### Change

`libs/docstruct/src/docstruct/manifest.py` now builds the specs once per class
with `functools.cache` and returns `copy.deepcopy` of the cached result. The
copy keeps the public function safe: a caller that mutates its specs cannot
change the next call. Behaviour, findings, ordering and error messages are
unchanged; only repeated introspection is removed.

The public docstring states the read-only cache contract. A regression test
mutates the first result and asserts the second call is unaffected.

### Measured effect

The same machine, the same coverage flags and the same suite commands as the
baseline:

The committed after-baseline is one final-tree run. A second final-tree run
took 271.35s, so the totals have substantial machine-load variance; the
docstruct result is stable across both.

| Suite | Before wall (s) | After wall (s) | Change |
|---|---:|---:|---:|
| Application | 157.23 | 116.46 | −25.9% |
| docstruct | 96.48 | 23.03 | −76.1% |
| SDK | 31.20 | 31.79 | +1.9% (within run-to-run variation) |
| core | 41.25 | 67.69 | +64.1% (load; not on the changed path) |
| **Total** | **326.17** | **238.96** | **−26.7%** |

The second final-tree run had docstruct at 19.14s and app at 197.52s, so the
overall percentage is not a stable constant. The slowest docstruct test went
from **23.59s to 2.31s** (10.2×) in the committed run and 2.05s in the repeat;
that is the measured effect the cache explains. The application and docstruct
suites exercise the manifest adapter. The SDK and core figures are dominated by
run-to-run variance and are not attributed to this PR.

Test counts match the delivered tree: 7,118 tests. The PR 1 instrumentation
tests (10) are not in this branch, and this PR adds four docstruct tests (three
boundary tests and the cache regression) plus three root report-consistency
tests. Coverage stayed at 87.9% (application), 87.0% (docstruct), 97.3% (SDK)
and 82.7% (core).

## 2. Close the three surviving `flood_guard` boundary mutants

### Problem

PR 3's mutation experiment scored `docstruct.fusion.flood` at 14/17 (82.3%).
The three survivors were real boundary gaps, not equivalent mutants:

| Mutant | Boundary |
|---|---|
| M005 | exactly `DEFAULT_MIN_BLOCKS` blocks |
| M011 | text with exactly `DEFAULT_SHORT` characters |
| M016 | guard triggered without dropping a block |

### Change

Three tests in `libs/docstruct/tests/test_flood.py`:

- `test_o_minimo_de_blocos_e_inclusivo`
- `test_o_comprimento_curto_e_inclusivo`
- `test_disparar_sem_descartar_nao_conta_pagina`

They are ordinary fast unit tests; the whole docstruct suite still completes in
about 14.5 seconds.

### Measured effect

The same mutation harness and the same 17 mutants:

| Measure | Before | After |
|---|---:|---:|
| Killed | 14 | 17 |
| Survived | 3 | 0 |
| Mutation score | 82.3% | **100%** |
| Experiment wall time | ~15s | ~17s |
| Mutants detected by exactly one test | M006, M007, M013, M015, M017 | M005, M006, M011, M016 |

Each new test is the only killer of one previously surviving mutant: M005,
M011 and M016. The experiment report is
[`mutation-flood-after.json`](mutation-flood-after.json).

## What this PR deliberately does not do

- **No test removal.** The overlap report found high similarity but no pairwise
  subset; the mutation matrix showed contracts and diagnostics that coverage
  cannot see. Removing a test would trade a measured gain for unmeasured risk.
- **No production behaviour change.** The cache changes performance only; the
  validation findings are identical.
- **No threshold or gate change.** Coverage floors and the required checks stay
  as they are.
- **No parallelism change.** Four workers remain the supported bound for the
  application suite; the library suites stay serial because they are now 14–45
  seconds each.

## Reproduction

With the PR 1 tooling merged:

```bash
# The full after-baseline (writes var/timings/baseline.json)
make test-baseline

# The before/after comparison
make test-baseline-compare BASELINE=var/timings/baseline.json

# The docstruct suite alone
(cd libs/docstruct && uv run --extra dev pytest --durations=25)
```

Without the PR 1 tooling, the equivalent command is:

```bash
uv run pytest -m "not e2e" -n 4 --dist worksteal --durations=25
(cd libs/docstruct && uv run --extra dev pytest --durations=25)
```

The mutations are reproduced with the PR 3 harness:

```bash
uv run python scripts/tests/mutation_report.py \
  --module libs/docstruct/src/docstruct/fusion/flood.py \
  --tests tests/test_flood.py --suite libs/docstruct \
  --source-root libs/docstruct/src \
  --coverage-file var/timings/coverage/docstruct/.coverage \
  --output var/mutation/flood-after.json
```

## Limitations

- **Machine-load variance is large.** The two final-tree runs took 238.96s and
  271.35s; the docstruct magnitude survives the variance, the aggregate
  percentage and the core change do not. Repeat measurements before treating a
  small delta as causal.
- **The cache assumes class hints do not change at runtime.** The document types
  are frozen at import; a dynamically redefined class is outside the contract.
  `functools.cache` also retains a strong reference to every class passed to the
  public `field_specs`; this is fine for the static types here but not for
  dynamically generated classes.
- **The mutation operator set is still limited.** 17/17 means the three
  boundary gaps are closed, not that the module detects every possible defect.
- **The application suite still has a long tail.** Its slowest test remains the
  VLM judge case; this PR does not target it, although the committed after-run
  recorded 35.84s and the repeat 87.22s (the PR 1 baseline recorded 52.19s), so
  machine variance or the shared manifest path both remain plausible
  explanations.
