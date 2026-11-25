# Differential fixtures of the canonical output (#849)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

The #640 migrations moved the enrichment steps into the plan, one step per
pull request (M2, M1, M3, M4a, M4b). Each kept a step-level differential
test, which shows the step is equivalent once planned. It does not show that
the whole pipeline is: M1's formula LaTeX gap (#846) was a regression between
steps. These fixtures compare the **final canonical document** of a run of
this tree with the one the core produced before each migration.

## How a case runs

`runner.py` runs a case the way `backend/service.py` runs a job: the PDDL
orchestrator's `execute` with a structured output, the paragraph merge, then
`build_canonical_document`. It uses only what core 0.3.11 already had, so the
same runner works on an older tree.

Every call the core makes leaves it over HTTP: the SDK's capability clients
and, with `AI_CLIENT=toolbox`, the agents' chats through the Toolbox VLM
gateway. `fake_toolbox.py` answers that boundary in process: it routes every
`httpx` client to a `MockTransport`, so nothing inside the core is patched.
Its answers are deterministic, and come from the case:

| Case key | Answers |
|---|---|
| `document` | `document.structure.extract`: a ProcessingManifest-compatible document |
| `vision` | the VLM, per element id (or `page-<n>`): a description, a region's `kind` and `formula_latex`, a table's `rows`; fields the case leaves out get a valid default from the response schema |
| `latex` | `math.recognize`, per formula id |
| `text_spans` | `document.text.spans`, per page |
| `tables` | `table.recognize`, per table id |

A rendered image does not say which region it shows, and a newer core may
downscale or re-encode it. So each `pdf.render` returns a solid colour that
indexes the clip it rendered. The VLM and `math.recognize` answers decode the
colour back to the clip, then to the element whose box holds its centre.

`math.convert` and `math.verbalize` echo the LaTeX (`spoken <latex>`), so a
change in what is sent shows in the output. A call the fake cannot answer is
recorded; the test fails on any.

## The cases

`build_cases.py` writes `cases/<name>/case.json` from the core's models:

| Case | What it covers |
|---|---|
| `text-and-picture` | a picture described (M1) |
| `tables` | a table read from its image, and one already structured (M2) |
| `formulas` | a formula without LaTeX markup, classified and read (M4a, M3); one with LaTeX; a picture the vision model reads as a formula (M1, #846) |
| `mostly-visual` | a page with no text content, whose placeholder visuals are described |
| `inline-math` | prose marked from the text layer's fonts (M4b), and a formula that reads its variables |

## The references

`references/<label>/` holds each case's normalized output recorded on the core
before a migration, and a `SOURCE.json` naming the commit:

| Label | Commit | Before |
|---|---|---|
| `core-0.3.11` | `9d433476` | M2 |
| `core-0.3.13` | `0cc303b5` | M1 |
| `core-0.3.14` | `da5c97b8` | M3 |
| `core-0.3.18` | `6781ff58` | M4a |
| `core-0.3.19` | `d2714cdf` | M4b |

Normalization drops what changes from run to run: timestamps, durations,
paths. It also drops what identifies or prices the planning state: the plan,
execution and manifest ids, the expected cost, and the document id that hashes
them.

`tests/test_differential_canonical.py` runs each case once on this tree and
compares it with every reference. A difference a later release made on purpose
is declared in the reference's `intended.json`:

```json
{
  "*": [{"kind": "added", "path": "/metadata/pddl_toolbox_availability/optional",
         "reason": "core 0.3.16 (#848): optional capability calls"}],
  "formulas": [{"kind": "changed", "path": "/sections/0/blocks/*/alt_text",
                "reason": "..."}]
}
```

`kind` is `added`, `removed` or `changed`. `path` is a JSON pointer in which
`*` matches any run of characters. Entries under `*` apply to every case. An
undeclared difference fails, and so does a declared one that no longer
happens.

## What the references show

When this harness was added (core 0.3.20):

- **M4a and M4b** changed no output: this tree matches `core-0.3.18` and
  `core-0.3.19` exactly.
- **Against `core-0.3.11` and `core-0.3.13`**, the differences are:
  - the availability report of #848 (core 0.3.16);
  - one more manifest revision where a description retypes an element (M1,
    core 0.3.14).
- **Against `core-0.3.14`**, the picture the vision model reads as a formula
  has its formula LaTeX again (`formula_recognition`). That is the gap of M1
  (#846), which M3 closed in 0.3.15: `core-0.3.14` is the one release without
  it. Reintroducing the gap fails the test against every other reference.

## Recording

```bash
uv run python -m tests.differential.build_cases       # after editing a case
uv run python scripts/record_differential_references.py --ref 9d433476 --label core-0.3.11
```

The script checks the commit out in a temporary git worktree, copies this
harness into it, and runs every case there with that tree's own locked
environment, plus Pillow, which the fake needs. Record every reference again
after changing a case. Add a reference before each later migration that
could change the output.

The fixtures do not cover a resume from an enrichment checkpoint yet: a resume
compares a run with itself, not with an older core, and the checkpoint format
changed between these releases (#836). It is #874.
