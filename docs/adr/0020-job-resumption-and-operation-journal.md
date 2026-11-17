# Resuming a job from its durable checkpoint

- **Status:** Accepted
- **Date:** 2026-11-14
- **Components:** core, Toolbox (through the operation identifiers of ADR-0019)
- **Issues:** #407, #380, #409

## Context

A job interrupted by an API restart is lost. `recover_pending_jobs`
(`backend/api/worker.py`) marks a job left in `processing` as failed, naming
the stage it was on, and a long document restarts from zero if the user submits
it again. The Toolbox result cache only helps once a run has finished, and a
retry after a restart used a new `operation_id`, so the Toolbox could not join
the work it had already done.

ADR-0019 defined `task_id`, `operation_id` and `attempt_id`, made the Toolbox
join a known operation, and left the core's durable journal to this issue. All
capabilities the document pipeline calls are idempotent (`execution.idempotent`
in the Toolbox contract, honoured by the SDK in #406); `dataset.sample` is the
only non-idempotent capability and the document pipeline does not call it.
Repeating an unfinished pipeline step is therefore safe; repeating a finished
one is only wasteful.

## Decision

### Checkpoints

The core must write one JSON checkpoint per pipeline phase, under
`DATA_DIR/jobs/<task_id>/checkpoints/`. The core writes them through the job's
`JobCheckpoints` port, which the service binds to the task id
(`FileJobCheckpoints`; [ADR-0016](0016-core-package.md), step 4):

| Phase | Written when | Holds |
|---|---|---|
| `media` | `media.inspect` returned (or degraded) | the inspection and its configuration |
| `manifest` | structural extraction passed the page limit, then as each enrichment object completes | the extracted manifest, kept current with the objects already finished |
| `enriched` | the enrichment steps finished | the enriched manifest |
| `plan` | a plan was built | the plan, the comparison, the manifest it was built from, the gate decision and the replan count |
| `execution` | after every plan step | the working manifest, the step results so far and `replan_required` |

A checkpoint must carry a schema version and the SHA-256 of its payload. It must
be replaced atomically, so a process killed mid-write leaves the previous
version, never a truncated one. A checkpoint from another version, with a
mismatched hash, or unreadable must not be used to resume; it is logged and the
job fails as it does today rather than continuing on data this build cannot
read.

Checkpoints exist only inside a job. The benchmark and the CLI call the
orchestrator without a task id and write none, keeping their behaviour
unchanged.

The checkpoint payloads are the pydantic documents the pipeline already carries
(`ProcessingManifest`, `NominalPlan`, `PlanningComparison`, `ExecutionReport`
steps); no second representation is introduced.

### Recovery

On startup, `recover_pending_jobs` must keep its rule for `cancelling` (the job
becomes `cancelled`) and for `queued` (the job is enqueued again). For a job left
`processing` it must:

1. re-enqueue the job when resumption is enabled
   (`JOB_RESUME_ON_RESTART`), the upload still exists, and every checkpoint is
   usable;
2. fail it as today, with the stage it was on, in every other case;
3. leave a job already back in the queue untouched, so a repeated recovery
   neither enqueues it twice nor invalidates its status and checkpoints.

A recovered job waiting in the queue has no in-memory task yet. It must still be
cancellable: the cancellation removes its queue entry, upload and checkpoints,
and records the terminal status as it does for a queue-only job.

A graceful shutdown is not a cancellation. The API must mark the process as
shutting down before it stops the queue worker, and an interrupted job must keep
its `processing` record, upload, checkpoints and operation ids. The next startup
then resumes it. Only an explicit user cancellation clears that state.

A resumed run must restore the durable progress the job shows (stage, progress,
start time), skip the one-time confirmation e-mail, and let the orchestrator
load the latest phase and continue. It must not change the executor's
semantics: the plan binding is validated against the manifest it was planned
from, `max_retries=0` and the fail-open behaviour for a failed
`execute-obligation` stay, `complete-job` still refuses an open obligation, the
replan budget has one owner, and `run_blocking` still waits.

Delivery is not checkpointed. A resume after the pipeline finished re-runs the
local and Toolbox exports from the completed canonical document; every export is
idempotent. The confirmation e-mail is never re-sent. A crash between sending
the result e-mail and recording `email_delivery` can still duplicate it, as
before this ADR.

Checkpoints must be removed when a job reaches a terminal state or is cancelled,
and swept by the periodic cleanup after the longest cache retention (7 days) so
a job that disappears without a terminal state does not leave data forever.

### Operation journal

The core must keep a durable mapping of `(task_id, logical slot)` to
`operation_id` in the same SQLite database as the job records. The registry must
reuse that id when the same logical call starts again, so a phase re-run after a
restart names the operation the Toolbox already knows and the Toolbox joins it
instead of running the provider twice (ADR-0019).

The journal stores identity only: the Toolbox owns the operation state and its
result. If the Toolbox no longer retains an operation, the repeat runs under the
same id, which is safe because the pipeline only names idempotent capabilities.
Rows are removed when the job ends and swept after 7 days otherwise.

The slots covered are the ones the core already names: the artifact upload, the
primary extraction and the secondary extraction. Extending coverage to other
Toolbox calls does not change this ADR.

## Consequences

- Restarting the API during extraction, enrichment, planning or plan execution
  continues the document from the last checkpoint. A graceful shutdown keeps the
  job resumable instead of marking it cancelled. An interruption inside one
  phase repeats only that phase's unfinished calls; the enrichment steps persist
  each completed object, so a restart skips them, and every operation is
  idempotent.
- A job without a usable checkpoint fails exactly as before, so the recovery
  message and the failure e-mail keep working for jobs killed before the first
  checkpoint.
- The checkpoint is one overwritten file per phase, not a growing history. Its
  size is the size of the manifest/plan it already holds; the cost is bounded by
  the number of plan steps.
- `JOB_RESUME_ON_RESTART=false` restores the old behaviour without a code
  revert.
- A Toolbox restart still loses its in-flight operation results; the core keeps
  the id but the retry runs the provider again. No durable cross-process
  operation journal exists in the Toolbox, and this ADR does not claim one.
- The journal adds one SQLite table to `history.db`; the checkpoints add one
  directory per job under `DATA_DIR`. Cleanup owns both.
- Compliance is checked by `tests/test_job_resume.py` (checkpoint integrity,
  recovery, executor continuation, restored progress and the journal reused
  across a simulated restart) and by the existing cancellation, queue and
  executor suites, which must pass unchanged.

## References

- #407 (this work), #380 and #409 (operation identifiers and cancellation,
  ADR-0019), #406 (retry only idempotent capabilities), #350 (local extraction
  deadline).
