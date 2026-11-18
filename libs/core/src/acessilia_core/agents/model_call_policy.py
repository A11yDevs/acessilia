"""Deadline margin shared by synchronous VisionAgent and DataAgent calls.

The clients' HTTP timeout applies per read, so a trickling provider can keep
the exchange alive. This margin lets an ordinary HTTP timeout arrive first
while bounding the asynchronous wait for one attempt. The configured timeout
also includes Toolbox VLM gateway slot wait when that backend is selected.

Timing out does not stop a running thread or release its connection and
per-call client. The application's dedicated runner retains its reservation
until that thread finishes, independently of the caller's event loop.
"""

CALL_DEADLINE_GRACE_SECONDS = 30


def model_call_deadline(timeout_seconds: float) -> float:
    return timeout_seconds + CALL_DEADLINE_GRACE_SECONDS
