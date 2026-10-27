"""Stop calling a model provider that keeps failing, for the rest of one job.

006.pdf v5 lost most of its descriptions to a provider that went down partway
through the job, and every remaining picture still paid up to two call
deadlines before it degraded. The breaker counts provider failures in a row
across the vision stages of one job (pictures, then tables); after
``threshold`` of them it opens and the remaining calls are skipped, recorded
as ``model_failed`` with the reason, so the job degrades at once instead of
waiting on each call.

Only a call that got no answer counts. An answer the job does not use (an
empty description, a table reading refused as worse) is the model working,
and resets the count.
"""

from __future__ import annotations

from backend.i18n import t
from backend.log_messages import LOG_PROVIDER_BREAKER_OPEN
from backend.tools.logger import logger


class ProviderBreaker:
    """Consecutive-failure counter shared by the vision calls of one job."""

    def __init__(self, threshold: int) -> None:
        """``threshold`` failures in a row open the breaker; 0 never opens it."""
        self.threshold = max(0, threshold)
        self._streak = 0

    @property
    def open(self) -> bool:
        """Whether calls should be skipped."""
        return self.threshold > 0 and self._streak >= self.threshold

    def skip_detail(self) -> str:
        """Why a call was skipped, for metadata["vision_failure_detail"]."""
        return f"skipped: the provider failed {self._streak} calls in a row"

    def record(self, answered: bool) -> None:
        """Count a call: an answer closes the breaker, no answer adds a failure."""
        if answered:
            self._streak = 0
            return
        was_open = self.open
        self._streak += 1
        if self.open and not was_open:
            logger.warning(t(LOG_PROVIDER_BREAKER_OPEN).format(failures=self._streak))

    def probe(self) -> None:
        """Let one more call through an open breaker; its failure opens it again."""
        if self.open:
            self._streak = self.threshold - 1
