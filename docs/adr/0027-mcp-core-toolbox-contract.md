# 0027. Versioned capability contracts, invoked over MCP, between the core and the Toolbox

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0027-mcp-core-toolbox-contract.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-22
- **Components:** core, SDK, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#632](https://github.com/A11yDevs/acessilia/issues/632)
- **Builds on:** [ADR-0004](0004-single-source-of-truth-for-contracts.md), [ADR-0006](0006-availability-and-failover.md), [ADR-0015](0015-artifact-reference-v1.md), [ADR-0019](0019-operation-identifiers-and-cancellation.md)

## Context

[#735](https://github.com/A11yDevs/acessilia/issues/735) sets the direction for
the refactoring stages #632, #639 and #640: the core plans and coordinates, the
Toolbox executes every capability, and the two talk through MCP, addressed by
capability. As measured on `develop` (`46f2fe7e`) and `acessilia-toolbox@main`:

- The core reaches the Toolbox only through REST, with one typed SDK client per
  capability (`acessilia_sdk.toolbox.clients.*`). Nothing in `libs/` or
  `backend/` speaks MCP.
- The Toolbox has an MCP facade (`acessilia_toolbox.api.mcp.ToolboxMCPServer`),
  but it is served only over stdio (`scripts/mcp_server.py`, hand-written
  JSON-RPC) and is not mounted on the HTTP API, so a remote core cannot use it.
- Its tools take a free-form `parameters` object and a `file` that is a local
  path or an `artifact_id`. No capability publishes a parameter schema:
  `capabilities/*.yaml` declare `input.schema` and `output.schema` as artifact
  schemas (for example `artifact/document@1`), plus `execution`, `semantics`
  and `providers`, and REST's `:execute` takes `parameters` as a JSON string.
- The MCP facade builds one tool per *latest* manifest, named
  `id.replace(".", "_")`, with the version in neither the name nor the schema.
  REST lists every version and `:execute` accepts `version`.
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

### Source of truth

- The versioned capability contracts the Toolbox publishes are the semantic
  source of truth (ADR-0004), independent of transport: identity and version,
  inputs and outputs, errors, idempotency, artifact references, operational
  states and cancellation semantics.
- MCP is the primary protocol for discovering and invoking capabilities
  between the core and the Toolbox. REST is a compatible interface derived from
  the same contracts. PDDL fragments add the semantics planning needs
  (preconditions, effects) without redefining the operational contract
  (ADR-0029).

### Transport

- The Toolbox must serve MCP over the Streamable HTTP transport on its HTTP
  API, under the same authentication as REST (the Toolbox API key).
- The Toolbox must state the MCP protocol revision it implements in its
  published contract. The SDK must refuse to negotiate a revision it does not
  support.
- stdio stays available for local agents; it is not a path for the core.

### Tools are capabilities

- Every catalogued capability **version** must be exposed as one MCP tool, and
  only catalogued capabilities may be exposed. The tool name is
  `{id}__v{version}` (for example `document.ocr__v1`): the id is kept as is,
  without replacing dots, and the double underscore cannot occur in a
  capability id, so names cannot collide. The tool also carries the id and the
  version in its metadata. An action bound to an older version stays
  invocable.
- The tool's input schema has two parts:
  - the **invocation controls** REST already exposes: `provider` (optional;
    ADR-0029 plans with provider availability), `language`, `no_cache`, and
    the input artifact as an `artifact/reference@1` value (ADR-0015). Over HTTP
    a tool must not accept a local file path.
  - the capability's **parameters**, described by a JSON Schema that the
    capability contract publishes. Today no capability publishes one, so this
    is a contract change in the Toolbox (ADR-0004, P7): each capability
    manifest gains a parameter schema, with a rule for provider-specific
    parameters (for example a per-provider schema keyed by provider id). Until
    a capability publishes its schema, its tool keeps a free-form
    `parameters` object, and the parity test reports it.
- A successful result carries, as `structuredContent`, the same envelope and
  provenance as the REST response for the same call. The tool's
  `outputSchema`, when declared, is that success envelope.
- A parity test in the Toolbox must check that the MCP tool list and the REST
  catalogue name the same capabilities, versions and schemas.

### Identifiers, progress, cancellation and errors

- The identifiers of ADR-0019 must travel in the request's `_meta`, under the
  reverse-DNS keys `io.github.a11ydevs/task-id`,
  `io.github.a11ydevs/operation-id` and `io.github.a11ydevs/attempt-id`, with
  the same meaning and validation as the headers. The prefix is the
  organisation's GitHub Pages domain reversed, so it cannot collide with other
  vendors, and it contains no label reserved by MCP (`mcp`,
  `modelcontextprotocol`).
- A client may request progress notifications; the Toolbox reports progress
  where the provider can measure it.
- Cancellation has two paths, because the MCP notification is fire-and-forget
  (a receiver may ignore it, it names a request id on one connection, and it
  can arrive after the response):
  - **fast path:** `notifications/cancelled` for a request in flight. The
    server maps the request id to the `operation_id` it received in that
    request's `_meta`, for the life of the session;
  - **durable path:** the ADR-0019 cancellation endpoint, by `operation_id`.
    The client must use it whenever the session that carried the request is
    gone (reconnection, failover) or the notification got no effect, and to
    cancel a job.
- Toolbox errors are tool results with `isError: true`. They carry the error
  envelope (code such as `invalid_input` or `provider_unavailable`, message,
  retryability) as JSON in `content` and under
  `_meta["io.github.a11ydevs/error"]`, never in `structuredContent`, which is
  reserved for the success envelope. The SDK reads the code from `_meta` and
  raises the same typed errors it raises for REST.

### Clients and sessions

- The SDK must offer a generic capability client: discover the catalogue,
  invoke a capability by id and version with its inputs and identifiers,
  follow progress and cancel.
- ADR-0006's failover and retry rules apply, with the rules a Streamable HTTP
  session adds:
  - a session (`Mcp-Session-Id`) belongs to one endpoint and is not portable.
    Failing over to another replica opens a new session with `initialize`, and
    a `404` for a session means re-initializing;
  - a request replayed after a broken stream or on another replica keeps its
    `operation_id`, so the Toolbox joins the known operation instead of running
    it twice (ADR-0019, `execution.idempotent`);
  - before replaying on a secondary, the client checks that the secondary's
    `tools/list` contains the bound `capability@version`, as the typed clients
    check the secondary's catalogue today (#429);
  - the catalogue snapshot used for planning comes from the primary and does
    not fail over silently, as `toolbox_gate` does today.
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

## Open decisions

This ADR stays `Proposed` until these are closed in review:

- **Parameter schemas.** The form of the per-capability parameter schema and
  the rule for provider-specific parameters is a Toolbox contract change. It
  closes when the Toolbox's owners accept it in `acessilia-toolbox`.
- **Cross-component review.** The Toolbox's owners review the MCP facade rules
  above (ADR process, step 5). After that, a follow-up pull request sets
  `Accepted`.

## Consequences

- One invocation path for the core, benchmarks, scripts and external agents.
  The planner can call a capability it knows only by id and version
  (ADR-0029).
- The Toolbox owns two facades over one executor; the parity test keeps them
  equal.
- Asynchronous, durable execution (#639: queues and workers) is not decided
  here. The synchronous call with progress defined above is the base it will
  extend, in a later ADR.
- Follow-up work, tracked in #735:
  - Toolbox: publish parameter schemas in the capability contracts; serve MCP
    over HTTP with one tool per `(id, version)`; accept artifact references;
    map the `_meta` identifiers, cancellation and the error envelope; add the
    parity test.
  - SDK: the generic MCP client with the session and failover rules above,
    with contract tests against a Toolbox fixture.
  - core: move the call sites to the generic client; an architecture test
    forbids new imports of typed clients.
- Compliance: the Toolbox parity test; `scripts/check_capability_contract.py`
  extended to the MCP tool list; `tests/test_architecture_layers.py` for the
  core's client imports.
