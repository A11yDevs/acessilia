# 0022. A shared export walker with consumer-owned rendering policy

Brazilian Portuguese: [português brasileiro](0022-export-walker-contract.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-17
- **Components:** docstruct
- **Issues:** [#371, E1.6](https://github.com/A11yDevs/acessilia/issues/371), [#161, D2](https://github.com/A11yDevs/acessilia/issues/161)

## Context

TXT, HTML, Markdown and Pandoc AST repeat section traversal. Their policies
differ: Markdown omits every heading matching the section title; the other
formats omit only the first matching legacy title. Profile filters and label
propagation also differ. The approved E1.0 baseline in PR #567 freezes these
differences. Sharing traversal must preserve them, as required by the
[latest review](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790).

## Decision

- `docstruct.export.walk` provides a pure, lazy depth-first walker and a typed
  visitor over the existing section/block dictionaries. It creates no second
  canonical document model and adds no runtime dependencies (ADRs [0002](0002-component-responsibilities.md)
  and [0004](0004-single-source-of-truth-for-contracts.md)).
- The visitor has eleven optional block callbacks, a mandatory callable
  `default` for unknown or unregistered types, and optional section entry/exit
  hooks. Each callback returns one result or `None`; aggregation belongs to the
  consumer. Falsey non-`None` results survive unchanged.
- A consumer-provided `select(block, context)` controls block inclusion. Without
  it, every block is visited. It does not prune child sections. Title omission,
  profiles, labels, document-level metadata and validation remain consumer policy.
- Frozen contexts expose original dictionaries, section paths/depth and original
  block indices. Legacy-title/alias properties delegate lazily to existing
  helpers. Callbacks must treat shared dictionaries as read-only; the walker
  does not mutate or defensively copy them. Consumer exceptions propagate.
- E1.6 introduces the API and test-only renderer compositions. Production
  migration is a separate E1.7 PR after review. Behaviour corrections stay in
  #161; strict export validation is not enabled here.

## Consequences

Traversal can be reused without imposing one format's policy on the others.
Consumers must explicitly select blocks and aggregate callback results.
Contract tests cover all schema types, ordering, fallback and context semantics;
test-only compositions compare all 30 characterized calls while the original
golden gate remains unchanged. Both run against the isolated wheel and in the
locked test container.

The additive API is versioned as docstruct 0.5.1: existing public signatures and
behaviour are unchanged, and it stays within the SDK's `>=0.5,<0.6` range.
Publishing a release follows the existing post-merge release process; this PR
does not publish it or change external consumers' pins.
