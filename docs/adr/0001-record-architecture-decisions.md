# 0001. Record architecture decisions

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0001-record-architecture-decisions.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-18
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152)

## Context

Decisions such as "the Toolbox does not depend on the SDK" or "the core has
no local fallbacks" were spread across issue threads, README files and pull
request reviews. Two repositories are involved, and each has its own
constitution. Contributors and coding agents had no single place to check a
decision before proposing a change, and a few documents had started to
contradict each other.

## Decision

- Cross-component architectural decisions are recorded as ADRs in
  `acessilia/docs/adr/`. That directory is their single source of truth.
- Each repository may keep ADRs about its own internals. They link to the
  cross-component ADRs instead of copying them.
- English is normative and every ADR has a `.pt-br.md` mirror written in the
  same pull request.
- A cross-component ADR is reviewed by the owners of every component it
  affects.
- An accepted ADR is not rewritten; a new ADR supersedes it.
- An exception to a constitution principle requires an ADR (see
  [README](README.md#process)).

## Consequences

- The constitution states principles and links to the ADR that details each
  one, so the two do not drift.
- Pull request reviews can point to an ADR instead of re-arguing a decision.
- Writing an ADR adds a small cost to structural changes; small, local changes
  do not need one.
