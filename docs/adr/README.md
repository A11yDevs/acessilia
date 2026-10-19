# Architecture Decision Records

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

An Architecture Decision Record (ADR) captures one significant architectural
decision: its context, the decision itself and its consequences. This
directory is the **single source of truth for decisions that cross component
boundaries** in the Acessilia ecosystem: the core (`backend/`), the SDK
(`libs/sdk`), docstruct (`libs/docstruct`) and the
[Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox).

Each repository may keep ADRs about its own internals. Those ADRs link to the
ones here instead of restating them.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-component-responsibilities.md) | Component responsibilities and dependency direction | Accepted |
| [0003](0003-remote-only-operational-capabilities.md) | Operational capabilities run remotely, without local fallbacks | Accepted |
| [0004](0004-single-source-of-truth-for-contracts.md) | One source of truth per contract | Accepted |
| [0005](0005-artifact-references.md) | Reference-oriented processing with `ArtifactRef` | Accepted |
| [0006](0006-availability-and-failover.md) | Availability through replicas; SDK failover as a secondary mechanism | Accepted |
| [0007](0007-manifest-model-and-mathml-conversion.md) | Canonical manifest model in docstruct; MathML only through `math.convert` | Accepted |

## Process

1. **When to write one.** Write an ADR for a decision that changes
   responsibilities or dependencies between components, adds or removes an
   execution mode (for example a local executor), changes a public contract, or
   is an exception to a principle of the [constitution](../constitution.md).
2. **Format.** Copy [template.md](template.md). Use the next free number and a
   short kebab-case slug in English: `NNNN-title.md`, with its mirror at
   `NNNN-title.pt-br.md`. Keep it short; link to issues and code for detail.
3. **Language.** English is normative. A `.pt-br.md` mirror is written in the
   same pull request, following principle 8 of the constitution.
4. **Status.** The status in the file is the state the ADR has once its pull
   request is merged, because that pull request's review is the ADR's review
   (step 5). A pull request that records a decision sets it to `Accepted`. Use
   `Proposed` only to merge an ADR whose decision is still open, so it can be
   discussed in follow-up pull requests. Later statuses are
   `Superseded by NNNN` and `Deprecated`. An accepted ADR is not rewritten: a
   changed decision gets a new ADR that supersedes it. Fixing typos and links
   is fine.
5. **Review.** A cross-component ADR is reviewed by the owners of every
   component it affects. Each team keeps its technical autonomy inside its own
   component.
6. **Exceptions.** An exception to a constitution principle is recorded as an
   ADR that states the justification, the scope (which capability, which
   deployment), the owner and the exit criterion. Without such an ADR, the
   principle applies.
