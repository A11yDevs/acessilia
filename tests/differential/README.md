# Differential fixtures of the canonical output (#849)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

The #640 migrations moved the enrichment steps into the plan, one step per
pull request (M2, M1, M3, M4a, M4b). Each kept a step-level differential
test, which shows the step is equivalent once planned. It does not show that
the whole pipeline is: M1's formula LaTeX gap (#846) was a regression between
steps. These fixtures compare the **final canonical document** of a run of
this tree with the one the core produced before each migration.

A reference is a golden master, not ground truth: it can keep a bug of its
release. Semantic quality is measured elsewhere, against ground truth (the
benchmarks of #619).

## Scope

What the cases establish is limited to what they run:

- eight synthetic documents, of one to three pages;
- one extraction provider, except `dual-provider` (`FUSION_MODE=dual`),
  which exercises the page adjudication, `select-table-source`, and a page
  routed to the secondary provider with `rescue-omitted`. `fuse-providers`
  and the text fusion (`dual-provider-fusion`) are not exercised;
- a Toolbox that answers, except in `degraded`, where `math.recognize` and
  `document.text.spans` are unavailable and the vision model fails on one
  picture. These are failures at call time (HTTP 503); the availability
  gate is off, so a capability the catalogue reports unavailable before
  planning (#848) is not exercised;
- pages that exist in the extraction only: every case runs on the same
  one-page `source.pdf`, and the fake answers the page count and the
  renders, so `multi-page` tests the pipeline's handling of pages and
  elements, not the extraction or rendering of a real multi-page PDF (the
  e2e tests on the dataset's documents cover that);
- the normalized canonical document: not the exports, not the number of
  calls.

The equivalence the references show holds for these cases only. A resume
from a checkpoint is #874.

## How a case runs

`runner.py` runs a case the way `backend/service.py` runs a job: the PDDL
orchestrator's `execute` with a structured output, the paragraph merge, then
`build_canonical_document`. It uses only what core 0.3.11 already had, so the
same runner works on an older tree.

**The run is hermetic** (`hermetic_environment`). Every variable the
backend's settings can read is removed first, including what `.env` loaded
into the process, and the server and task locale are pinned to `en_US`,
so the messages an output carries (a warning, a fallback alt text) do not
follow `LANG` or an earlier test. The settings then get their defaults plus the harness's
`ENVIRONMENT`, with `DATA_DIR` and `TEMP_DIR` in a temporary directory, and
the whole environment is restored afterwards. A reference recorded in a bare
worktree and a run in a developer's tree therefore see the same
configuration.

**The Toolbox is a fake.** Every call the core makes leaves it over HTTP: the
SDK's capability clients and, with `AI_CLIENT=toolbox`, the agents' chats
through the Toolbox VLM gateway. `fake_toolbox.py` answers that boundary in
process: it routes every `httpx` client to a `MockTransport`, so nothing
inside the core is patched. Its answers come from the case:

| Case key | Answers |
|---|---|
| `document` | `document.structure.extract`: a ProcessingManifest-compatible document |
| `vision` | the VLM, per element id (or `page-<n>`): a description, a region's `kind` and `formula_latex`, a table's `rows` |
| `latex` | `math.recognize`, per formula id (`""`: it reads nothing) |
| `text_spans` | `document.text.spans`, per page |
| `secondary_document` | the secondary provider's extraction, with `FUSION_MODE=dual`. Only the primary provider (`primary_provider`, `docling`) and the secondary (`FUSION_SECONDARY_PROVIDER`, else `secondary_provider`, else `mineru`) get one; any other is unhandled. A region only the secondary extracted is matched against its boxes |
| `judge` | per page (`page-<n>`), the `pB` of `document.adjudicate.page` for that page's image |
| `failures` | what fails on purpose: `capabilities` answered 503, `vision` element ids the model refuses; recorded in `refused`. The test and the recording both require exactly the declared failures |
| `environment` | settings the case sets over the harness's (`FUSION_MODE=dual`) |

**Regions are matched by colour.** A rendered image does not say which region
it shows, and a newer core may downscale or re-encode it. So each `pdf.render`
returns a solid colour that indexes the clip it rendered (up to 512 per
case). The VLM and `math.recognize` decode the colour back to the clip:
- a clip covering the page is `page-<n>`;
- a smaller clip is the element it overlaps most (intersection over union).

**The fake is strict.** It refuses, and records as unhandled, any of these:
- an image it did not render;
- a clip no element matches, or that two elements match equally;
- an element the case gives no answer for;
- an answer the agent's own response schema rejects;
- a capability it does not serve.

Only the fields a case's answer leaves out get a default, and the whole
answer is still validated. The test fails on any unhandled call.

`math.convert` and `math.verbalize` echo the LaTeX (`spoken <latex>`), so a
change in what is sent shows in the output.

## The cases

`build_cases.py` writes `cases/<name>/case.json` from the core's models:

| Case | What it covers |
|---|---|
| `text-and-picture` | a picture described (M1) |
| `tables` | a table read from its image, and one already structured (M2) |
| `formulas` | a formula without LaTeX markup, classified and read (M4a, M3); one with LaTeX; a picture the vision model reads as a formula (M1, #846) |
| `mostly-visual` | a page with no text content, whose placeholder visuals are described |
| `inline-math` | prose marked from the text layer's fonts (M4b), and a formula that reads its variables |
| `multi-page` | a picture, a formula and a table read from its image, each on its own page |
| `dual-provider` | two providers on three pages: a page adjudicated, a table adopted from the secondary and marked again (M4b's `inline_math_stale`), a page routed to the secondary whose primary-only paragraph, with inline math, `rescue-omitted` puts back (#887) |
| `degraded` | `math.recognize` and `document.text.spans` unavailable, and the vision model failing on one of two pictures: the formula falls back to the vision model, the inline math is unavailable, one picture is left undescribed with a warning |

## The references

`references/<label>/` holds each case's normalized output recorded on the core
before a migration:

| Label | Commit | Before |
|---|---|---|
| `core-0.3.11` | `9d433476` | M2 |
| `core-0.3.13` | `0cc303b5` | M1 |
| `core-0.3.14` | `da5c97b8` | M3 |
| `core-0.3.18` | `6781ff58` | M4a |
| `core-0.3.19` | `d2714cdf` | M4b |

**Normalization** drops only these JSON pointers:
- `/source/path`, the run's temporary path;
- the plan, execution and manifest ids and the expected cost under
  `/metadata`, which identify or price the planning state and change with
  every migration by design;
- the document's `/id`, which hashes them.

A field of the same name anywhere else is still compared.

**`refused`** and **`cacheable`** are recorded too. `refused` must equal
the case's `failures` when a reference is recorded and on this tree;
`cacheable` (whether the backend would cache the result) is checked on this
tree only, since its contract may evolve: `degraded` must not be cached.

**`calls`** counts the capabilities each run asked for. It is diagnostic only
and is not compared: a later core may call less on purpose. For example, M4b
stopped reading the text layer of a document with no prose to mark.

**`SOURCE.json`** names the commit and core version, and the harness's
identity (`runner.identity`): SHA-256 digests of the runner, the fake, the
cases and the source PDF, and the versions of the packages the fake adds
(Pillow and jsonschema, pinned). The test refuses a reference whose identity
differs from this tree's, so a harness change calls for recording again. The
comparison (`compare.py`) is not part of the identity.

## Declared differences

`tests/test_differential_canonical.py` runs each case once on this tree and
compares it with every reference. A difference that a later release made on
purpose is declared in the reference's `intended.json`, **with the value it
allows**:

```json
{
  "*": [{"kind": "added", "path": "/metadata/pddl_toolbox_availability/optional",
         "expected": {}, "reason": "core 0.3.16 (#848): ..."}],
  "formulas": [{"kind": "changed", "path": "/metadata/pddl_manifest_revision",
                "expected": 3, "reason": "core 0.3.14 (M1): ..."}]
}
```

The fields of an entry:
- `kind` is `added`, `removed` or `changed`.
- `path` is a JSON pointer in which `*` matches any run of characters. Use
  `*` only where the position, not the field, varies.
- `expected` is required for `added` and `changed`: a later change of the
  same field is not accepted with it.
- `was` is optional for `removed`, and checks the value that went.
- Entries under `*` apply to every case.

An undeclared difference fails, and so does a declared one that no longer
happens.

## What the references show

When this harness was added (core 0.3.20):

- **M4a and M4b** changed no output: this tree matches `core-0.3.18` and
  `core-0.3.19` exactly.
- **Against `core-0.3.11` and `core-0.3.13`**, the differences are:
  - the availability report of #848 (core 0.3.16);
  - one more manifest revision where a description retypes an element (M1,
    core 0.3.14).
- **Against `core-0.3.14`**, the differences are:
  - the same availability report of #848;
  - the picture the vision model reads as a formula has its formula LaTeX
    again (`formula_recognition`, `formula_text_layer`). That is the gap of
    M1 (#846), which M3 closed in 0.3.15: `core-0.3.14` is the one release
    without it;
  - the surrounding text of that picture has the nearby formula's extracted
    text again, since M3 runs the formula LaTeX after the descriptions, as
    before 0.3.14.

Reintroducing the #846 gap fails the test against every other reference.

The cases added for #876 (core 0.3.23) show:

- **`multi-page`** matches every reference.
- **`dual-provider`**:
  - the adopted table's math cell is marked again (`$s_0\in\mathbb{R}$`) by
    every release since 0.3.12, where the pass of #599 marked it after the
    plan; M4b (0.3.20) does it as a planned step, at the cost of one more
    manifest revision. `core-0.3.11`, before #599, left the cell unmarked:
    declared;
  - the formula of the page routed to the secondary is read from the
    secondary's region the same way by every release;
  - every recorded release loses the paragraph that only the primary
    provider kept on the routed page; core 0.3.24 (#887) rescues it, with
    its inline math, and every reference declares it.
- **`degraded`** matches every reference but `core-0.3.14`, where the
  pictures' surrounding text differs, the same M3 difference as in
  `formulas`.

## Recording

```bash
uv run python -m tests.differential.build_cases       # after editing a case
uv run python scripts/record_differential_references.py --ref 9d433476 --label core-0.3.11
```

The script checks the commit out in a temporary git worktree, copies the
harness into it, and runs the cases there with that tree's own locked
environment, plus the pinned packages the fake needs. Nothing is published
until every case ran and the fake answered every call; then the reference is
swapped whole.

- **Recording every case** replaces the reference and drops the cases that no
  longer exist. It keeps `intended.json`, which is written by hand.
- **Recording some cases** (`... core-0.3.11 formulas`) replaces only those,
  and is refused when the reference was recorded with another commit or
  harness.

## Maintaining the references

- **Adding a reference.** Add one before each later migration, or any change
  that could move the output. Record it from the commit just before the
  change merges.
- **Updating a reference.** Record again only when the harness or a case
  changes (the identity check says when). Never record again to turn the CI
  green: a new difference is either a regression to fix or an intended
  change to declare, with its value and the release that made it.
- **Retiring a reference.** Retire one once a newer reference covers the
  same migration and its declarations only repeat the newer one's. Say so in
  the pull request.
