# 0018. The core uses only the SDK's public API

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0018-core-uses-sdk-public-api.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-13
- **Components:** core, SDK
- **Issues:** [#470](https://github.com/A11yDevs/acessilia/issues/470), [#402](https://github.com/A11yDevs/acessilia/issues/402)

## Context

[ADR-0017](0017-operational-sdk-and-agentic-core.md) makes the SDK a public,
versioned API: scripts, benchmarks and other front ends call it without the
core, and its operations need a changelog and deprecation. The core is one of
those callers. If it reached into the SDK's internals, an internal change in
the SDK would break the core without being a breaking change of the API, and
the SDK could not refactor freely. #402 called this "ADR B": the core depends
only on the SDK's public API.

What the code says today, measured on develop at cfa45001:

- **Every SDK module already declares `__all__`**, except the package itself
  (`__version__`) and the `python -m` entry point (`acessilia_sdk.__main__`).
  Those lists are complete: they cover everything the SDK means to offer,
  including the client classes, their capability ids and the errors.
- **The README's "Public API" table summarizes them.** Every name it lists is
  in its module's `__all__`, but it does not list every exported name (for
  example, `ToolboxPdfValidateClient` is exported and was missing from the
  clients row).
- **The core already uses only exported names.** A scan of `backend/`,
  `scripts/` and `tests/` found 181 uses of SDK names in 52 files. It covered
  imports, attributes read through an imported SDK module, and dotted string
  paths such as `monkeypatch.setattr` targets, and none is outside a module's
  `__all__`. Keeping to the public API costs nothing today.

Options considered:

1. **No rule.** The core may use any SDK name. Nothing breaks today, but
   nothing stops the coupling either.
2. **The README table is the public API.** It is prose, it summarizes, and it
   names methods and fields that are not module names, so it cannot be checked
   exactly.
3. **Each module's `__all__` is the public API**, with the README as a
   summary checked against it.

## Decision

Proposed: option 3.

- **The SDK's public API is what each SDK module lists in `__all__`**, plus the
  public SDK modules themselves. A name outside `__all__` is internal: it may
  change or disappear in any release, without a changelog entry.
- **Every SDK API module declares `__all__`.** The package (`acessilia_sdk`)
  and entry points (`__main__`) are not API modules.
- **The core, its scripts and its tests use only public names**: in imports,
  in attributes read through an SDK module, and in dotted string paths, such as
  a patch target. A method or attribute of a public class is public with the
  class.
- **A reviewed exception** is allowed only in the guard's `ALLOWED` map, with
  its reason; an exception nothing uses any more fails the guard. There is
  none today.
- **The README's Public API table is a summary**: every name it lists must be
  in its module's `__all__`, so it never promises something the code does not
  export.
- **Adding a name to `__all__` makes it public** and goes in the SDK's
  changelog. When the core needs an internal name, the fix is to export it
  (with a changelog entry), not to add an exception.

## Consequences

- **Easier:**
  - the SDK can change its internals without breaking the core;
  - what the core relies on is listed in one place, and a reviewer sees an
    added export in the SDK's diff.
- **Harder:**
  - the core cannot borrow an SDK helper without exporting it first;
  - a new SDK module must declare `__all__`.
- **Compliance:**
  - `tests/test_sdk_public_api.py` (core): every SDK use in `backend/`,
    `scripts/` and `tests/` is public; no SDK API module lacks `__all__`; no
    exception is stale. A self-test checks the guard on each kind of use;
  - `libs/sdk/tests/test_public_api.py` (SDK): every name the README table
    lists is in its module's `__all__`. It also runs in the `SDK alone` job.
- **Follow-up:** none required. The guard is blocking from the start, because
  the measured cost is zero (decision of 2026-11-13). If this ADR is rejected,
  the two tests are removed.
