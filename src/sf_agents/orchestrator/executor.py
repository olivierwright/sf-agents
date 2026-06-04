"""The executor: run a validated plan DAG with auditing and review routing.

Steps run in dependency order. Each step's args are resolved against upstream
outputs (the ``{"$from": ..., "path": ...}`` reference convention), the primitive
is built from the registry and wired to the run's audit logger, and its output is
captured. A step that raises is retried once. Any output whose confidence falls
below the floor is routed to a human-review stub (recorded, not silently
dropped). Connector-style outputs are indexed as *sources* for the verifier.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import Config, get_config
from ..governance.audit_logger import AuditLogger
from ..primitives.base import AuditHook, PrimitiveInput, PrimitiveOutput
from .events import EventType, OnEvent, RunEvent
from .planner import Plan, Planner
from .registry import Registry

logger = logging.getLogger("sf_agents.executor")


@dataclass
class ExecutionResult:
    """Everything produced by running a plan."""

    run_id: str
    order: list[str]
    outputs: dict[str, PrimitiveOutput]
    sources: dict[str, dict[str, Any]]
    review_queue: list[dict[str, Any]] = field(default_factory=list)
    final_step_id: Optional[str] = None
    audit_path: Optional[str] = None

    @property
    def final_output(self) -> Optional[PrimitiveOutput]:
        if self.final_step_id is None:
            return None
        return self.outputs.get(self.final_step_id)


class Executor:
    """Run a :class:`Plan` against a :class:`Registry`."""

    def __init__(
        self,
        registry: Registry,
        *,
        config: Optional[Config] = None,
        audit_logger: Optional[AuditLogger] = None,
        on_event: Optional[OnEvent] = None,
        tracer: Optional[Any] = None,
    ) -> None:
        self._registry = registry
        self._config = config or get_config()
        self._audit = audit_logger
        self._on_event = on_event
        self._tracer = tracer  # RunTracer instance or None

    def _emit(self, event_type: EventType, payload: dict) -> None:
        """Emit a :class:`RunEvent` to the registered callback, if any.

        Silently swallows any exception raised by the callback so that an
        observer can never crash a run.
        """
        if self._on_event is None:
            return
        try:
            self._on_event(RunEvent(type=event_type, payload=payload))
        except Exception:  # noqa: BLE001
            logger.debug("on_event callback raised; ignoring", exc_info=True)

    def run(self, plan: Plan, *, run_id: str = "run") -> ExecutionResult:
        """Execute ``plan`` and return an :class:`ExecutionResult`."""
        self._emit(EventType.RUN_STARTED, {"run_id": run_id})
        order = Planner.topological_order(plan)
        self._emit(
            EventType.PLAN_READY,
            {
                "steps": [s.as_dict() for s in order],
                "explanation": plan.explanation,
                "source": plan.source,
                "step_count": len(order),
            },
        )
        if self._tracer:
            self._tracer.set_plan(plan)

        hook: Optional[AuditHook] = self._audit.record if self._audit else None
        outputs: dict[str, PrimitiveOutput] = {}
        sources: dict[str, dict[str, Any]] = {}
        review_queue: list[dict[str, Any]] = []
        _current_step_id: Optional[str] = None

        try:
            for step in order:
                _current_step_id = step.step_id
                primitive = self._registry.build(step.primitive, hook)
                args = _resolve(step.args, outputs)
                inp = PrimitiveInput(args=args)
                self._emit(
                    EventType.STEP_STARTED,
                    {"step_id": step.step_id, "primitive": step.primitive},
                )
                if self._tracer:
                    self._tracer.log_step_start(
                        step_id=step.step_id,
                        primitive=step.primitive,
                        version=getattr(primitive, "version", ""),
                        input_args=dict(args),
                    )
                t_start = _now_ms()
                output = self._invoke(primitive, inp, run_id=run_id, step_id=step.step_id)
                if self._tracer:
                    self._tracer.log_step_done(
                        step_id=step.step_id,
                        output=output,
                        duration_ms=_now_ms() - t_start,
                    )
                outputs[step.step_id] = output
                _index_source(output, sources)
                audit_rec = output.metadata.get("audit", {})
                self._emit(
                    EventType.STEP_FINISHED,
                    {
                        "step_id": step.step_id,
                        "primitive": step.primitive,
                        "confidence": output.confidence,
                        "duration_ms": audit_rec.get("duration_ms"),
                        "citations": [c.as_dict() for c in output.citations],
                        "issues": list(output.issues),
                    },
                )

                if output.confidence < self._config.confidence_floor:
                    review_entry = _human_review(
                        step.step_id, step.primitive, output, self._config.confidence_floor
                    )
                    review_queue.append(review_entry)
                    self._emit(EventType.HUMAN_REVIEW_REQ, review_entry)

        except Exception as exc:
            self._emit(
                EventType.RUN_ERROR,
                {"message": str(exc), "step_id": _current_step_id},
            )
            raise

        result = ExecutionResult(
            run_id=run_id,
            order=[s.step_id for s in order],
            outputs=outputs,
            sources=sources,
            review_queue=review_queue,
            final_step_id=order[-1].step_id if order else None,
            audit_path=str(self._audit.path) if self._audit else None,
        )
        self._emit(
            EventType.RUN_FINISHED,
            {
                "run_id": run_id,
                "step_count": len(order),
                "review_queue_size": len(review_queue),
                "final_step_id": result.final_step_id,
            },
        )
        return result

    def _invoke(
        self,
        primitive,
        inp: PrimitiveInput,
        *,
        run_id: str,
        step_id: str,
    ) -> PrimitiveOutput:
        try:
            return primitive(inp, run_id=run_id, step_id=step_id)
        except Exception as first:  # noqa: BLE001 - retry once, then surface
            logger.warning("step %s failed (%s); retrying once", step_id, first)
            return primitive(inp, run_id=run_id, step_id=step_id)


# -- reference resolution ---------------------------------------------------- #
def _resolve(value: Any, outputs: dict[str, PrimitiveOutput]) -> Any:
    """Recursively replace ``$from`` references with upstream output values."""
    if isinstance(value, dict):
        if "$from" in value:
            step_id = value["$from"]
            path = value.get("path", "")
            if step_id not in outputs:
                raise KeyError(f"Reference to step {step_id!r} which has no output yet")
            return _dig(outputs[step_id].as_dict(), path)
        return {k: _resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, outputs) for v in value]
    return value


def _dig(obj: Any, path: str) -> Any:
    """Follow a dotted ``path`` (supports list indices) into ``obj``."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(f"Cannot resolve path segment {part!r} in {type(cur).__name__}")
    return cur


# -- source indexing + human review ------------------------------------------ #
def _index_source(output: PrimitiveOutput, sources: dict[str, dict[str, Any]]) -> None:
    """Record a connector-style payload as a verifiable source."""
    payload = output.payload
    if not isinstance(payload, dict):
        return
    document = payload.get("document")
    if not isinstance(document, str):
        return
    entry = sources.setdefault(document, {})
    pages = payload.get("pages")
    if isinstance(pages, list):
        entry.setdefault("pages", set())
        for p in pages:
            if isinstance(p, dict) and isinstance(p.get("page"), int):
                entry["pages"].add(p["page"])
    if isinstance(payload.get("row_count"), int):
        entry["row_count"] = payload["row_count"]
    elif isinstance(payload.get("rows"), list):
        entry["row_count"] = len(payload["rows"])


def _now_ms() -> float:
    return time.monotonic() * 1000.0


def _human_review(
    step_id: str, primitive: str, output: PrimitiveOutput, floor: float
) -> dict[str, Any]:
    """Stub: flag a low-confidence output for human review (records, no block)."""
    logger.warning(
        "step %s (%s) confidence %.2f below floor %.2f -> human review",
        step_id,
        primitive,
        output.confidence,
        floor,
    )
    return {
        "step_id": step_id,
        "primitive": primitive,
        "confidence": output.confidence,
        "floor": floor,
        "issues": list(output.issues),
    }
