# Operation identifiers and remote cancellation

Status: Accepted

## Context

A job may run several remote Toolbox calls: an artifact upload, a primary
structural extraction and, in dual fusion, a secondary extraction. Today none
of them can be named. When a user cancels a job, the core can stop waiting at
the extraction deadline (`TOOLBOX_EXTRACTION_TIMEOUT_SECONDS`, #350), but the
Toolbox keeps the provider thread running and the execution slot occupied.

Retries and failover make a request identifier insufficient: a read timeout
does not tell the client whether the first request ran, and two independent
Toolbox endpoints share no deduplication. The same decision is needed by
resumption (#407) and by the observability work (#385). The constitution
requires an ADR for a contract that crosses the core, the SDK and the Toolbox,
and #380 asked for this decision before implementation.

## Decision

### Identifiers

- **`task_id`** identifies one core job. The core generates it (the job id
  already visible in the API) and keeps it for the whole job. It is not reused
  by another job.
- **`operation_id`** identifies one logical remote operation: one artifact
  upload or one capability invocation. The core generates a fresh UUIDv4 for
  each such operation. It stays the same across SDK retries and failover of
  that operation.
- **`attempt_id`** identifies one HTTP attempt. The SDK generates a fresh
  UUIDv4 immediately before each request, including each retry and each
  endpoint tried. It changes even when `operation_id` does not.

The identifiers travel in request headers, not in the capability form or the
published capability contract:

```text
X-Acessilia-Task-Id: <task_id>
X-Acessilia-Operation-Id: <operation_id>
X-Acessilia-Attempt-Id: <attempt_id>
```

They are optional for compatibility. A caller that omits them keeps the old
behaviour: no registry entry and no remote cancellation. When an
`operation_id` is present, `task_id` is required. Identifiers are 1–200
log-safe characters (`[A-Za-z0-9][A-Za-z0-9._:-]*`); an invalid or missing
required identifier is `400 invalid_input`, before any provider runs.

### Scope and authentication

Cancellation uses the existing Toolbox API key. The endpoint requires both
`operation_id` and `task_id`, and answers `404 operation_not_found` when the
pair is unknown or belongs to another task. It never reveals whether another
task owns an id. There is no cross-task cancellation, and the core never sends
another job's identifiers.

### Toolbox states

The Toolbox keeps a process-local registry while an operation is running:

| State | Meaning |
|---|---|
| `running` | The request owns the provider execution or is waiting for it. |
| `cancel_requested` | A cancel request matched the operation. This is an acknowledgement, not proof that a provider stopped computing. |
| `cancelled` | The request observed the cancel request before publishing a result. No result is stored, cached or returned. |
| `finished` | The request completed before a cancel request was observed. |
| `failed` | The request failed before a cancel request was observed. |

`POST /v1/operations/{operation_id}:cancel` returns the current state. A
running operation moves to `cancel_requested`; a terminal operation keeps its
state. Cancelling is idempotent: repeating the request is allowed and returns
the same state. A duplicate `operation_id` with the same `task_id` joins the
running or terminal operation instead of executing the provider again; this is
what keeps an idempotent retry from running twice. The completed response (or
error) is retained only while the process-local registry retains it.

For an interruptible provider, cancellation closes or aborts the upstream
request. An in-process provider may only check a cooperative flag. Work that
cannot be interrupted is allowed to finish, but its result is discarded and
never stored, cached, published or returned. The execution slot is released
when the thread actually ends, not when the cancel endpoint returns; the
response therefore distinguishes `cancel_requested` from `cancelled`.

### Core behaviour

When the user cancels a job, the core:

1. records the local cancellation immediately, as today;
2. asks the Toolbox to cancel every active operation of the job, with one
   short wall-clock budget (`TOOLBOX_CANCEL_TIMEOUT_SECONDS`, default 5 s);
3. records one best-effort state in the job: `none`, `requested`, `finished`,
   `not_found` or `failed`;
4. keeps `run_blocking` waiting for the extraction thread, as today.

A failed or timed-out cancel request is logged and recorded; it is not an
error, a retry of the original capability, a failover, a download search or an
input resend. It does not delay the API more than the configured budget. The
local job can still reach `cancelled` when the extraction deadline ends.

`cancelled` in the core means the local job finished. It does not by itself
claim that the provider stopped; only a Toolbox state read or a confirmed
`cancelled` execution would. The core reports `requested` rather than
promising a remote abort.

## Consequences

- The operation identifiers are an additive Toolbox API contract. Old Toolbox
  versions ignore the headers and return `404` for cancellation; the core
  reports `not_found` or `failed` and keeps working.
- The registry is in memory and per process. With independent endpoints or a
  load balancer that does not route the cancel request to the replica that owns
  the operation, cancellation can return `not_found`. A shared, durable
  operation journal is #407, not this ADR.
- After a Toolbox or core restart, in-flight operations are lost to the
  registry. Recovery keeps today's rule: a job left `cancelling` becomes
  `cancelled`, and remote work is left to its configured timeouts.
- A retry that joins an operation may wait as long as the owner request; it
  does not consume a second execution slot. A cancel of the owner propagates
  to the joined attempts.
- Operation identifiers are not a cache key and do not change capability
  results, retry policy or failover policy. They only identify and, when
  possible, stop an operation.
- The core attaches identifiers to the extraction upload, primary and
  secondary calls. Other Toolbox calls keep the legacy behaviour until they
  get an operation owner; extending coverage does not change this contract.
- Remote cancellation is best-effort. Work that a provider cannot interrupt
  continues to consume its slot until it ends, even though its result is
  discarded.

## References

- #350 (local extraction deadline), #407 (resume and repeated operations),
  #409 (this cancellation), #380 (operation identifiers), #406 (retry only
  idempotent capabilities).
- Acessilia Toolbox issues #146 (who may act on an operation) and #137
  (sidecar lifecycle).
