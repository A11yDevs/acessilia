# 0021. Bounded model-call execution owned by the application

Brazilian Portuguese: [português brasileiro](0021-bounded-model-call-execution.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-15
- **Components:** core, service
- **Issue:** [#276](https://github.com/A11yDevs/acessilia/issues/276), step 2 after PR #552

## Context

An abandoned model await cannot kill the provider thread. The default executor
can be exhausted by these calls and is joined by `asyncio.run()`. Merely limiting
ThreadPoolExecutor workers leaves its submission queue unbounded. Cancelled
closures can therefore retain images, agents and clients.

## Decision

- The core defines `ModelCallRunner`; agents receive it by composition. The
  service owns one process-scoped implementation across transient event loops.
- The service passes explicit `ModelCallLimits` from `MODEL_CALL_WORKERS` and
  `MODEL_CALL_MAX_PENDING` at creation. These are process setup, not per-run
  CoreConfig settings. Agents read no new settings (ADR-0016).
- Submit at most the worker count to ThreadPoolExecutor. Hold extra admitted
  work in a bounded removable FIFO. Reject immediately at capacity with
  `ModelCallRejected`, without adding hidden retries.
- Copy context per submission; include queue wait in the deadline and check
  expiry again before inference. Cancellation removes pending closures. A
  running abandoned call retains capacity until its invocation finishes and
  cannot publish a late result. `ModelCallTimeout` distinguishes the deadline
  from the provider's own timeout.
- Keep prompts, schemas and retry/degradation policies in the agents/pipeline.
  General blocking work keeps its executor and cancellation semantics. Core
  synchronous inspection bridges preserve request context in their helper thread.
- API/CLI shutdown closes admission, discards pending work and wakes pending
  and active awaiters with `ModelCallClosed`, without joining model threads.
  Active provider threads continue, retain their reservations until completion
  and have their late results discarded. Do not replace a closed owner while
  its workers remain. Neither
  `shutdown(wait=False)` nor closing a loop kills threads or guarantees immediate
  interpreter exit: Python still joins them. A permanently stalled provider may
  require external process termination.
- Localized logs and snapshots expose active reservations, pending/abandoned
  calls, rejections, expirations, queue wait and execution duration (#385).

The orchestrator required no runner at first and obtained the service owner
when none was supplied, like its CoreConfig bridge. ADR-0016's step 3 removed
both: `execute(..., config=, model_calls=)` requires the run's runner
(ADR-0016's step 4 then added the required `ports=`).
Standalone callers can pass and close their own runner. AgentOS chat agents remain
outside this execution path.
The service process talks to one model provider (its `AI_CLIENT`), so the
service's runner is also the bound per provider across runs: runs at once add
up their stages' `VISION_CONCURRENCY`, but never exceed `MODEL_CALL_WORKERS`
calls at the provider (#547). A standalone caller that runs several
`ModelConfig` in one process with one runner shares that bound among their
providers, which is stricter, never looser. A bound across processes or hosts
is outside the core: with `AI_CLIENT=toolbox`, it belongs to the Toolbox's
gateway; Ollama and OpenRouter have no gateway of ours, so their own limits
apply. See the [architecture](../architecture.md).

Follow-up (#590). The queue's concurrency and `VISION_CONCURRENCY` multiply:
`jobs at once × VISION_CONCURRENCY` calls may arrive together, and the runner
must admit them or reject the excess. Keeping the immediate rejection above,
the service derives `MODEL_CALL_MAX_PENDING` from that product when the
variable is unset or -1 (at least the historical 4) and warns at startup, without
refusing it, when an explicit value cannot cover the configured jobs. The
warning names the exact pending capacity that closes the gap. Over capacity is
a degraded mode, not an unsafe one, and the stages may use fewer calls than
their bound. The formula assumes a job's enrichment subplans stay sequential, so
one stage bound applies at a time; parallel subplans would need a new aggregate
budget (#828). Sizing the admission capacity does not make multi-job execution
safe, so `QUEUE_MAX_CONCURRENT` above 1 stays gated behind the explicit
`QUEUE_MULTI_JOB_EXPERIMENTAL=true` opt-in until #238 W1 supplies per-source
fairness, a public cancellation API and the memory/failure-isolation decisions
(#830). The settings validation, the queue factory and the queue constructor
enforce the same invariant.

A rejection is admission pressure, not provider health. It is retried once
like a timeout, without consuming an answer attempt; if it persists, the stage
records `admission_rejected` (pictures, tables, formulas), leaves the shared
breaker untouched, and keeps the run out of the cache so a rerun can retry it.
A closed runner raises the `ModelCallClosed` subtype instead: it is lifecycle,
not capacity pressure, so the agents do not retry it and the stages abort
rather than record a recoverable degradation. A closed runner also wakes
pending and active awaiters with the same subtype.

Retry composition (#590 review). The budgets are independent and bounded: one
admission retry per agent call, one timeout retry, two rate-limit retries, and
the answer/validation attempts inside the agent; then the document-level
`_retry_failed` pass gives each failed picture/table one more try after
`VISION_RETRY_PASS_DELAY_SECONDS`; a misread table has its own reread budget.
An admission rejection creates no per-table wait, consumes no answer attempt and
does not open the breaker.

## Consequences and verification

Core capacity, `VISION_CONCURRENCY`, gateway/provider slots and whole-job duration
are separate limits. This bounds local retention and isolates unrelated work.
`tests/test_model_call_executor.py` verifies deadlines, cancellation, saturation,
the bound shared by runs at once on separate event loops (#547),
retained reservations, late results, independent `run_blocking`, concurrent
locales, synchronous handlers/transient loops and owner shutdown/restart with
event-blocked providers. `tests/test_model_call_capacity.py` and
`libs/core/tests/test_model_call_admission.py` cover the #590 sizing check and
the rejection/reason semantics. Existing agent, table and cancellation suites
preserve the surrounding policies.
