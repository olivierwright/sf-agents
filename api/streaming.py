"""Run store and SSE streaming helpers.

Architecture
------------
* ``RunStore`` is a simple in-process store that holds every active/completed
  run keyed by ``run_id``.
* Each run owns an ``asyncio.Queue[RunEventModel | None]`` — the sentinel
  ``None`` signals end-of-stream to any waiting SSE consumer.
* The background thread running the recipe calls ``on_event``, which puts
  serialised events onto the queue using ``asyncio.run_coroutine_threadsafe``.
* The SSE endpoint drains the queue with ``async for``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from sf_agents.orchestrator.events import RunEvent

from .events import RunEventModel, RunStatus

logger = logging.getLogger("sf_agents.api.streaming")


@dataclass
class RunRecord:
    run_id: str
    recipe: str = ""
    question: str = ""
    strategy: str = "thorough"
    status: str = "pending"          # pending | running | waiting_for_input | done | error
    result: dict[str, Any] | None = None
    error: str | None = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    loop: asyncio.AbstractEventLoop | None = None
    # Human-in-the-loop: pause/resume
    clarification_event: threading.Event = field(default_factory=threading.Event)
    clarification_answer: Optional[str] = None
    pending_clarification: Optional[dict[str, Any]] = None

    def to_status(self) -> RunStatus:
        return RunStatus(
            run_id=self.run_id,
            recipe=self.recipe,
            question=self.question,
            strategy=self.strategy,
            status=self.status,
            result=self.result,
            error=self.error,
        )


class RunStore:
    """Thread-safe in-memory run registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, RunRecord] = {}

    def create(
        self,
        recipe: str = "",
        question: str = "",
        strategy: str = "thorough",
        run_id: str | None = None,
    ) -> RunRecord:
        rid = run_id or str(uuid.uuid4())
        record = RunRecord(run_id=rid, recipe=recipe, question=question, strategy=strategy)
        with self._lock:
            self._runs[rid] = record
        return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_all(self) -> list[RunStatus]:
        with self._lock:
            return [r.to_status() for r in self._runs.values()]


# Module-level singleton, shared by all routes.
run_store = RunStore()


def make_on_event(record: RunRecord) -> Any:
    """Return a thread-safe ``on_event`` callback for the given RunRecord.

    The callback is invoked from the background worker thread and safely
    enqueues a ``RunEventModel`` onto the asyncio queue that lives in the
    event-loop thread.
    """

    def _on_event(ev: RunEvent) -> None:
        if record.loop is None or record.loop.is_closed():
            return
        model = RunEventModel(
            type=ev.type.value,
            payload=ev.payload,
            timestamp=ev.timestamp,
        )
        asyncio.run_coroutine_threadsafe(_put(record.queue, model), record.loop)

    return _on_event


async def _put(q: asyncio.Queue, item: Any) -> None:
    await q.put(item)


async def sse_generator(record: RunRecord) -> AsyncGenerator[str, None]:
    """Drain a run's event queue as SSE-formatted strings.

    Yields ``data: <json>\\n\\n`` lines.  Stops when the sentinel ``None``
    is dequeued (run finished or errored) or after a 5-minute idle timeout.
    """
    import json

    TIMEOUT = 300  # seconds

    while True:
        try:
            item = await asyncio.wait_for(record.queue.get(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("SSE stream for %s timed out after %ss", record.run_id, TIMEOUT)
            break

        if item is None:
            # End-of-stream sentinel
            break

        yield f"data: {json.dumps(item.model_dump())}\n\n"
