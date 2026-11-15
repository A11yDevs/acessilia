"""Deadline margin shared by synchronous VisionAgent and DataAgent calls.

The clients' HTTP timeout applies per read, so a trickling provider can keep
the exchange alive. This margin lets an ordinary HTTP timeout arrive first
while bounding the asynchronous wait for one attempt. The configured timeout
also includes Toolbox VLM gateway slot wait when that backend is selected.

Timing out does not stop a running thread or release its connection and
per-call client. The event loop's default executor can still wait for it on
shutdown; isolated execution and bounded admission remain step 2 of #276.
"""

CALL_DEADLINE_GRACE_SECONDS = 30
