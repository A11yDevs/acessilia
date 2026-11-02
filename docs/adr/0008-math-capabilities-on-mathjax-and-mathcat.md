# 0008. The math capabilities run on MathJax and MathCAT

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0008-math-capabilities-on-mathjax-and-mathcat.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-20
- **Components:** Toolbox, SDK, core
- **Issues:** [toolbox#64](https://github.com/A11yDevs/acessilia-toolbox/issues/64), [toolbox#65](https://github.com/A11yDevs/acessilia-toolbox/pull/65), [toolbox#66](https://github.com/A11yDevs/acessilia-toolbox/pull/66), [#184](https://github.com/A11yDevs/acessilia/issues/184), [#193](https://github.com/A11yDevs/acessilia/pull/193)
- **Supersedes:** the provider named in decision 2 of [ADR-0007](0007-manifest-model-and-mathml-conversion.md) (`pure-math` with `latex2mathml`); the rest of ADR-0007 stands.

## Context

[ADR-0007](0007-manifest-model-and-mathml-conversion.md) decided that the core
obtains MathML and the spoken text of formulas only through the Toolbox
capabilities `math.convert` and `math.verbalize`, via the SDK. It named the
implementation behind them: the `pure-math` provider, with `latex2mathml` for
the conversion and a regex verbalizer.

Before the core switched to those capabilities, the Toolbox measured whether
they were at least as good as the core's local code they would replace
([toolbox#64](https://github.com/A11yDevs/acessilia-toolbox/issues/64)):

- 48 formulas were converted by five tools: the core's test formulas plus 30
  constructs common in teaching material.
- The results were spoken by MathCAT in pt-BR.

The measurement showed that:

- **Both verbalizers dropped content silently.** The `pure-math` regex rules
  and the core's own `formula_tools` did. For example, `\frac{d}{dx}\sin x=\cos x`
  became "d, dividido por d x x igual a x" in the core.
- **`latex2mathml` produced invalid MathML.** It failed for `aligned`, which
  Nougat output uses, and it supports neither mhchem (`\ce`) nor
  `\operatorname`.
- **MathJax 3 had the best coverage.** It handled everything, including mhchem.
  The only problem left was `\xrightarrow`, which is a MathCAT bug.
- **MathCAT speaks from the structure of the MathML.** It is MIT licensed and
  is the engine replacing MathPlayer in NVDA. It has gained Brazilian
  Portuguese rules, and it also produces math braille, including CMU, the code
  used in Brazil.

## Decision

**`math.convert` (`latex-to-mathml`) and `math.verbalize` are served by the
`math-speech` provider, an HTTP adapter for the `math-speech` sidecar.** The
sidecar runs **MathJax 3** for LaTeX → MathML and **MathCAT** for MathML →
speech (and braille). The `pure-math` provider, its regex verbalizer and
`latex2mathml` are removed from the Toolbox, with no fallback: there is one
converter and one verbalizer.

- **Contracts unchanged.** `math.convert@1` still returns `mathml@1`, and
  `math.verbalize@1` still returns `verbalized@1` in pt-BR (ADR-0007).
  `math.verbalize` takes optional `style` (`ClearSpeak` by default,
  `SimpleSpeak`) and `verbosity` (`Terse`, `Medium` by default, `Verbose`).
- **Pinned and traceable.** MathJax and the MathCAT commit are pinned in the
  image. The sidecar's `/version` enters the execution cache key, and a golden
  file with the exact pt-BR speech of 24 formulas fails the image build when
  an upgrade changes any of them, so new speech is reviewed on purpose.
- **Hardened input.** MathJax runs without the TeX packages that would reach
  HTML exports or load code at run time (`html`, `require`, `autoload`,
  `setoptions`), and without `noerrors`/`noundefined`, so bad LaTeX is an
  error the caller can act on.
- **Explicit errors.** Unparseable LaTeX is `400` (`invalid_input`), and an
  unavailable sidecar is `503`. Both reach the core as SDK errors; the core
  decides what to do, with no local fallback
  ([ADR-0003](0003-remote-only-operational-capabilities.md)).
- **Reverse direction stays in-process.** `mathml-to-latex` keeps the existing
  best-effort mapper inside the Toolbox (`providers/mathml_latex.py`), because
  MathJax has no TeX output.

## Consequences

- **Nothing changes in the core's code.** The core keeps calling the
  capabilities, not a provider. The SDK's default `toolbox_math_provider` is
  `math-speech` (#193).
- **Better speech now.** The spoken alternatives the core puts in its exports
  follow the structure of the formula, for example "d sobre d x, seno de x; é
  igual a cosseno de x".
- **The sidecar must run wherever math is enabled.** Its image is built and
  published by the Toolbox's `Sidecars` workflow, like the other sidecars
  (audit finding A7). Until it runs, both capabilities answer `503`.
- **Known gaps in MathCAT's pt rules** are recorded in the golden file as they
  are. Examples: "maiúscula e" instead of "E maiúsculo", and `\mid` spoken as
  "divide". `\xrightarrow` fails in every language. These are fixed upstream
  or overridden locally, never by reintroducing a second verbalizer.
- **Open, not decided here:**
  - The sidecar already produces CMU braille, but no capability exposes it
    yet. A `math.braille` capability, or a parameter of a new
    `math.verbalize` version, needs its own decision.
  - Verbalizing languages other than pt-BR needs a language parameter in a
    new version of `math.verbalize` (ADR-0007).
