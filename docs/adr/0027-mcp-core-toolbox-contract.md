# 0027. MCP is the contract between the core and the Toolbox

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0027-mcp-core-toolbox-contract.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-22
- **Components:** core, SDK, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#632](https://github.com/A11yDevs/acessilia/issues/632)
- **Builds on:** [ADR-0004](0004-single-source-of-truth-for-contracts.md), [ADR-0006](0006-availability-and-failover.md), [ADR-0015](0015-artifact-reference-v1.md), [ADR-0019](0019-operation-identifiers-and-cancellation.md)

## Context

[#735](https://github.com/A11yDevs/acessilia/issues/735) sets the direction for
the refactoring stages #632, #639 and #640: the core plans symbolically, the
Toolbox executes every capability, and the two talk through MCP, addressed by
capability. As measured on `develop` (`46f2fe7e`) and `acessilia-toolbox@main`:

- The core reaches the Toolbox only through REST, with one typed SDK client per
  capability (`acessilia_sdk.toolbox.clients.*`). Nothing in `libs/` or
  `backend/` speaks MCP.
- The Toolbox has an MCP facade (`acessilia_toolbox.api.mcp.ToolboxMCPServer`),
  but it is served only over stdio (`scripts/mcp_server.py`, hand-written
  JSON-RPC) and is not mounted on the HTTP API, so a remote core cannot use it.
- Its tools take a free-form `parameters` object and a `file` that is a local
  path or an `artifact_id`. The capability's published parameter schema is not
  the tool's input schema.
- The operation identifiers of ADR-0019 travel only as HTTP headers
  (`X-Acessilia-*`); MCP has no equivalent yet.

#639 put "replace REST with MCP" out of scope, and #632 drew "REST / MCP" as
interchangeable. Keeping both as first-class client paths would mean two
contracts to keep equal (ADR-0004), and would leave the generic, capability
addressed access that planning needs (#640, ADR-0029) without a transport.

Options considered:

1. **Keep REST, typed clients per capability.** No new transport, but every new
   capability needs SDK code, and the planner cannot invoke a capability it only
   knows by id.
2. **A generic REST client by capability id.** Solves addressing, but builds a
   second discovery and invocation contract next to the MCP one the Toolbox
   already publishes for agents.
3. **MCP over HTTP as the primary path, REST kept for compatibility and
   operations.** One invocation contract for the core, scripts and external
   agents. Chosen.

## Decision

### Transport

- The Toolbox must serve MCP over the Streamable HTTP transport on its HTTP
  API, under the same authentication as REST (the Toolbox API key).
- The Toolbox must state the MCP protocol revision it implements in its
  published contract. The SDK must refuse to negotiate a revision it does not
  support.
- stdio stays available for local agents; it is not a path for the core.

### Tools are capabilities

- Every capability in the catalogue must be exposed as one MCP tool, and only
  catalogued capabilities may be exposed. The tool carries the capability id
  and its exact version.
- The tool's input schema must be the capability's published parameter schema
  (ADR-0004). No free-form `parameters` object.
- Inputs that are artifacts must be `artifact/reference@1` values
  (ADR-0015). Over HTTP a tool must not accept a local file path.
- A tool's result must carry the same envelope and provenance as the REST
  response for the same call, as structured content.
- A parity test in the Toolbox must check that the MCP tool list and the REST
  catalogue name the same capabilities, versions and schemas.

### Identifiers, progress, cancellation and errors

- The identifiers of ADR-0019 must travel in the request's `_meta`, under the
  keys `acessilia/task_id`, `acessilia/operation_id` and
  `acessilia/attempt_id`, with the same meaning and validation as the headers.
- A client may request progress notifications; the Toolbox reports progress
  where the provider can measure it.
- The MCP cancellation notification for a request must cancel the operation
  in the same way as the ADR-0019 cancellation endpoint.
- Toolbox errors must reach the client as tool errors whose structured content
  holds the Toolbox error code (`invalid_input`, `provider_unavailable`, ...),
  so the SDK raises the same typed errors it raises for REST.

### Clients

- The SDK must offer a generic capability client: discover the catalogue,
  invoke a capability by id and version with its inputs and identifiers,
  follow progress and cancel. The failover and retry rules of ADR-0006 apply
  unchanged.
- The SDK must not make a heavy dependency mandatory for this (constitution,
  P2). Whether it uses the official MCP package as an optional extra or a
  minimal client of its own is left to the implementing pull request.
- The core must invoke Toolbox capabilities only through that generic client.
  The existing typed clients become thin wrappers over it, and then are
  deprecated. No new typed client per capability is added.

### REST

- REST stays for compatibility, health and readiness, artifact upload and
  download, and operations. No capability may be available on only one of the
  two transports.

## Consequences

- One invocation path for the core, benchmarks, scripts and external agents.
  The planner can call a capability it knows only by id (ADR-0029).
- The Toolbox owns two facades over one executor; the parity test keeps them
  equal.
- Asynchronous, durable execution (#639: queues and workers) is not decided
  here. The synchronous call with progress defined above is the base it will
  extend, in a later ADR.
- Follow-up work, tracked in #735:
  - Toolbox: serve MCP over HTTP, derive tool schemas from the capability
    schemas, accept artifact references, map `_meta` identifiers and
    cancellation, add the parity test.
  - SDK: the generic MCP client, with contract tests against a Toolbox fixture.
  - core: move the call sites to the generic client; an architecture test
    forbids new imports of typed clients.
- Compliance: the Toolbox parity test; `scripts/check_capability_contract.py`
  extended to the MCP tool list; `tests/test_architecture_layers.py` for the
  core's client imports.
