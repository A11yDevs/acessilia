from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class CorrelationContext:
    trace_id: str
    run_id: str
    session_id: str
    entity_type: str
    entity_id: str

    @classmethod
    def for_agno_run(
        cls,
        *,
        entity_type: str,
        entity_id: str,
        session_id: str,
    ) -> "CorrelationContext":
        return cls(
            trace_id=uuid.uuid4().hex,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def event_fields(self) -> dict[str, str]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
        }

    def attributes(self) -> dict[str, str]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
        }
