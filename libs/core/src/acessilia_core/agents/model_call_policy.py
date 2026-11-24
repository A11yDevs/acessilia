"""Deadline margin and retry budgets shared by synchronous VisionAgent/DataAgent calls.

The clients' HTTP timeout applies per read, so a trickling provider can keep
the exchange alive. This margin lets an ordinary HTTP timeout arrive first
while bounding the asynchronous wait for one attempt. The configured timeout
also includes Toolbox VLM gateway slot wait when that backend is selected.

Timing out does not stop a running thread or release its connection and
per-call client. The application's dedicated runner retains its reservation
until that thread finishes, independently of the caller's event loop.

Retry composition (#590 review). The budgets are independent and bounded:
one admission retry per agent call (``ADMISSION_RETRIES``), one timeout retry,
two rate-limit retries and the answer/validation attempts in the agent; the
document-level ``_retry_failed`` pass then gives each failed picture/table one
more try after ``VISION_RETRY_PASS_DELAY_SECONDS``; a misread table has its own
reread budget. An admission rejection consumes no answer attempt, does not
open the provider breaker, and does not create a per-table wait.
"""

CALL_DEADLINE_GRACE_SECONDS = 30

#: A local admission rejection (``ModelCallRejected``) gets one retry, like a
#: call that ran out of time. It says the runner is busy, nothing about the
#: image or the provider, so it must not consume an answer attempt (#590).
ADMISSION_RETRIES = 1

#: Seconds before the retry of a rejected call. A worker may finish in this
#: window and free both the worker and a pending slot; one retry bounds the
#: extra pressure the retry itself adds.
ADMISSION_RETRY_SECONDS = 1.0


def model_call_deadline(timeout_seconds: float) -> float:
    return timeout_seconds + CALL_DEADLINE_GRACE_SECONDS
