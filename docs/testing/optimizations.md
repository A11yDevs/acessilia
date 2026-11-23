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

| Suite | Before wall (s) | After wall (s) | Change |
|---|---:|---:|---:|
| Application | 157.23 | 90.91 | −42.2% |
| docstruct | 96.48 | 14.48 | −85.0% |
| SDK | 31.20 | 16.83 | −46.1% |
| core | 41.25 | 44.65 | +8.2% (noise; not on the changed path) |
| **Total** | **326.17** | **166.87** | **−48.8%** |

The JUnit totals moved from 310.32s to 158.75s (−48.8%). The slowest docstruct
test went from **23.59s to 2.10s** (11.2×). The application, docstruct and SDK
suites all exercise the manifest adapter; the core change is within run-to-run
variation and is not attributed to this PR.

Test counts differ by the delivered work, not by removal: the PR 1 instrumentation
tests (10) are not in this branch, and this PR adds four docstruct tests (three
boundary tests and the cache regression). Coverage stayed at 87.9% (application),
87.0% (docstruct), 97.3% (SDK) and 82.7% (core).

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
| Mutants detected by exactly one test | M006, M007, M013, M015, M017 | M005, M006, M011, M013, M015, M016, M017 |

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

- **One run per measurement.** The absolute seconds vary with machine load; the
  direction and the docstruct magnitude are large enough to survive that
  variance, the core +8% is not.
- **The cache assumes class hints do not change at runtime.** The document types
  are frozen at import; a dynamically redefined class is outside the contract.
- **The mutation operator set is still limited.** 17/17 means the three
  boundary gaps are closed, not that the module detects every possible defect.
- **The application suite still has a long tail.** Its slowest test remains the
  VLM judge case; this PR does not change it.
