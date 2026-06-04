"""Run-event model emitted by the executor for observability.

Each :class:`RunEvent` has an :class:`EventType`, a typed ``payload`` dict and
an ISO-8601 UTC timestamp. The executor emits events via an optional
``on_event`` callback; callers that do not supply a callback see no behaviour
change — zero overhead, zero import cost on the hot path.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


class EventType(str, enum.Enum):
    """Ordered lifecycle stages emitted by :class:`~sf_agents.orchestrator.executor.Executor`."""

    RUN_STARTED = "run_started"
    PLAN_READY = "plan_ready"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    HUMAN_REVIEW_REQ = "human_review_req"
    HUMAN_CLARIFICATION_NEEDED = "human_clarification_needed"
    STEP_ABSENCE_CERTIFIED = "step_absence_certified"
    VERIFICATION_DONE = "verification_done"
    RUN_FINISHED = "run_finished"
    RUN_ERROR = "run_error"


@dataclass
class RunEvent:
    """A single observability event emitted during plan execution.

    Attributes:
        type: The lifecycle stage this event represents.
        payload: Stage-specific data (see :class:`EventType` docs for keys).
        timestamp: ISO-8601 UTC instant the event was created.
    """

    type: EventType
    payload: dict[str, Any]
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


#: Convenience type alias for the ``on_event`` callback parameter.
OnEvent = Callable[[RunEvent], None]
