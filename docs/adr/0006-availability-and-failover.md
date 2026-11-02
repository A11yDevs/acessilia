# 0006. Availability through replicas; SDK failover as a secondary mechanism

- **Status:** Accepted
- **Date:** 2026-10-18
- **Components:** core, SDK, Toolbox, infrastructure
- **Issues:** [#150](https://github.com/A11yDevs/acessilia/issues/150), [#152](https://github.com/A11yDevs/acessilia/issues/152) (P6)

## Context

With local fallbacks removed
([ADR-0003](0003-remote-only-operational-capabilities.md)), the core depends
on the Toolbox being reachable. The Toolbox is already designed to be
stateless: artifacts live in object storage and caches in Valkey (Toolbox
constitution, principles 2 and 6). It also allows technical failover between
equivalent replicas (principle 5). Client-side failover between independent
Toolbox deployments was added to the SDK in
[#153](https://github.com/A11yDevs/acessilia/pull/153).

## Decision

**Primary mechanism: replicas behind a load balancer.**
- A Toolbox deployment runs stateless, compatible replicas behind one load
  balancer.
- The replicas share the artifact store (MinIO/S3) and the cache and locks
  (Valkey), so every `ArtifactRef` stays valid whichever replica answers.
- The core and the SDK see a single `base_url` (`TOOLBOX_BASE_URL`) that
  points at the balancer.

**Responsibilities:**

| Component | Responsible for |
|---|---|
| Toolbox | Compatible replicas, health checks, distributed execution, idempotent capabilities |
| Infrastructure | Load balancing, shared storage, failure recovery |
| SDK | Timeouts, bounded retries with backoff (idempotent calls only), uniform error mapping |
| Core | What to do when a capability is unavailable: fail the step, or degrade it visibly as a business decision |

**Secondary mechanism: SDK failover across independent deployments.**
- The SDK's multi-endpoint failover (`endpoints=`) is reserved for
  independent Toolbox deployments, for example another site.
- It moves to the next endpoint only when an instance could not serve the
  request (timeout, network error, 503, 504). 4xx errors and contract
  violations are raised at once.
- It uses a secondary endpoint only if that endpoint's catalogue publishes the
  capability at the expected contract version, for the requested provider.
- When every endpoint fails, it reports every cause in one error
  (`ToolboxUnavailable`).
- Automatic re-upload of an artifact unknown to another deployment is not a
  failover mechanism. It is off by default (`resend_file_on_missing_artifact`),
  because it adds traffic and complexity and risks inconsistent artifacts.

**No silent fallbacks.** No path silently produces a result through a
different implementation. Failovers are observable: the SDK calls an
`on_failover` hook and the core logs it.

## Consequences

- **Infrastructure work:** a deployment with replicas, a balancer and shared
  MinIO/Valkey is needed. It is tracked as an infrastructure issue in the
  #152 backlog.
- **#150 F1:** keeps `TOOLBOX_BASE_URL` as the single primary endpoint. An
  optional `TOOLBOX_BASE_URLS` serves only independent deployments.
- **Verified today:** `libs/sdk/tests/test_failover.py` covers failover
  triggers, skipping incompatible secondaries, bounded retries and backoff,
  the combined error, and resend being off by default.
- **Planned verification:** an end-to-end check with two Toolbox replicas
  behind a balancer, where stopping one replica must not fail a job.
