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
  and active awaiters with `ModelCallRejected`, without joining model threads.
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
Standalone callers can pass and close their own runner. AgentOS chat agents and provider scheduling (#547) remain
outside this execution path. See the [architecture](../architecture.md).

## Consequences and verification

Core capacity, `VISION_CONCURRENCY`, gateway/provider slots and whole-job duration
are separate limits. This bounds local retention and isolates unrelated work.
`tests/test_model_call_executor.py` verifies deadlines, cancellation, saturation,
retained reservations, late results, independent `run_blocking`, concurrent
locales, synchronous handlers/transient loops and owner shutdown/restart with
event-blocked providers. Existing agent, table and cancellation suites preserve
the surrounding policies.
