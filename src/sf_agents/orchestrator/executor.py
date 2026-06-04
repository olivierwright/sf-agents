"""The executor: run a validated plan DAG with auditing and review routing.

Steps run in dependency order. Each step's args are resolved against upstream
outputs (the ``{"$from": ..., "path": ...}`` reference convention), the primitive
is built from the registry and wired to the run's audit logger, and its output is
captured. A step that raises is retried once. Any output whose confidence falls
below the floor triggers an interactive human clarification request: the run
pauses, a targeted question is asked, and execution resumes with the answer
stored for downstream synthesis. Connector-style outputs are indexed as
*sources* for the verifier.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..config import Config, get_config
from ..governance.audit_logger import AuditLogger
from ..primitives._llm import complete
from ..primitives.base import AuditHook, PrimitiveInput, PrimitiveOutput
from .events import EventType, OnEvent, RunEvent
from .planner import Plan, Planner
from .registry import Registry

logger = logging.getLogger("sf_agents.executor")

# Signature: (step_id, primitive, output, question) -> human answer str
AskHuman = Callable[[str, str, PrimitiveOutput, str], str]


@dataclass
class ExecutionResult:
    """Everything produced by running a plan."""

    run_id: str
    order: list[str]
    outputs: dict[str, PrimitiveOutput]
    sources: dict[str, dict[str, Any]]
    review_queue: list[dict[str, Any]] = field(default_factory=list)
    clarifications: list[dict[str, Any]] = field(default_factory=list)
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
        ask_human: Optional[AskHuman] = None,
    ) -> None:
        self._registry = registry
        self._config = config or get_config()
        self._audit = audit_logger
        self._on_event = on_event
        self._tracer = tracer  # RunTracer instance or None
        self._ask_human = ask_human  # optional human-in-the-loop callback

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
        clarifications: list[dict[str, Any]] = []
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
                    if self._ask_human is not None:
                        question = _generate_clarification_question(
                            step.step_id, step.primitive, output, plan.explanation
                        )
                        self._emit(
                            EventType.HUMAN_CLARIFICATION_NEEDED,
                            {
                                "step_id": step.step_id,
                                "primitive": step.primitive,
                                "confidence": output.confidence,
                                "floor": self._config.confidence_floor,
                                "issues": list(output.issues),
                                "question": question,
                            },
                        )
                        answer = self._ask_human(step.step_id, step.primitive, output, question)
                        helped = not _user_cant_help(answer)
                        confidence_before = output.confidence
                        retry_output: Optional[PrimitiveOutput] = None

                        if helped:
                            # Retry the step with the analyst's hint injected
                            try:
                                hint_args = dict(args)
                                hint_args["context_hint"] = answer
                                hint_inp = PrimitiveInput(args=hint_args)
                                t_retry = _now_ms()
                                retry_output = self._invoke(
                                    primitive, hint_inp,
                                    run_id=run_id, step_id=step.step_id,
                                )
                                if retry_output.confidence > output.confidence:
                                    # Improved — adopt the retried output
                                    if self._tracer:
                                        self._tracer.log_step_done(
                                            step_id=step.step_id,
                                            output=retry_output,
                                            duration_ms=_now_ms() - t_retry,
                                        )
                                    outputs[step.step_id] = retry_output
                                    output = retry_output
                                    logger.info(
                                        "step %s: retry improved confidence %.2f → %.2f",
                                        step.step_id,
                                        clarifications[-1]["confidence"] if clarifications else 0,
                                        retry_output.confidence,
                                    )
                                else:
                                    retry_output = None  # no improvement, discard
                            except Exception as retry_exc:  # noqa: BLE001
                                logger.warning(
                                    "step %s: retry with hint failed: %s", step.step_id, retry_exc
                                )

                        clarifications.append({
                            "step_id": step.step_id,
                            "primitive": step.primitive,
                            "confidence_before": confidence_before,
                            "confidence_after": retry_output.confidence if retry_output else confidence_before,
                            "issues": list(output.issues),
                            "question": question,
                            "answer": answer,
                            "helped": helped,
                            "retried": retry_output is not None,
                        })
                    else:
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
            clarifications=clarifications,
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


_CANT_HELP_PHRASES = (
    "don't know", "dont know", "do not know", "figure it out", "not sure",
    "no idea", "skip", "idk", "n/a", "na", "just continue", "keep going",
    "doesn't matter", "doesn't matter", "dont care", "don't care",
)


def _user_cant_help(answer: str) -> bool:
    """Return True when the analyst's answer signals they cannot provide useful guidance."""
    lowered = answer.lower().strip()
    return not lowered or any(p in lowered for p in _CANT_HELP_PHRASES)


def _generate_clarification_question(
    step_id: str,
    primitive: str,
    output: PrimitiveOutput,
    plan_context: str,
) -> str:
    """Generate a short, plain-language clarifying question for the human analyst.

    The question must be immediately actionable — no document jargon, no
    multi-part structure. It tells the analyst exactly what was found, what is
    missing, and offers a clear escape hatch ("or type 'skip' to continue").
    """
    # Build a plain-English summary of what was found vs missing
    payload = output.payload or {}
    found_items: list[str] = []
    missing_items: list[str] = []
    if isinstance(payload, dict):
        for d in payload.get("definitions", []):
            found_items.append(d.get("term", ""))
        for s in payload.get("waterfall_steps", []):
            found_items.append(f"waterfall step {s.get('rank','?')}")
        for c in payload.get("covenants", []):
            found_items.append(c.get("type", ""))
    # Pull missing from issues text
    for issue in output.issues:
        if "No definition extracted for:" in issue:
            raw = issue.replace("No definition extracted for:", "").strip().rstrip(".")
            missing_items.extend(t.strip() for t in raw.split(","))

    found_str = ", ".join(found_items[:4]) if found_items else "nothing"
    missing_str = ", ".join(missing_items[:4]) if missing_items else "some items"

    prompt = (
        "You are helping an investor analyse a structured finance deal.\n\n"
        f"An automated step ('{step_id}') searched the document and found: {found_str}.\n"
        f"It could NOT find: {missing_str}.\n"
        f"Confidence score: {output.confidence:.0%}.\n\n"
        "Write ONE plain, short question (max 2 sentences) asking the analyst where to "
        "look for the missing information. Do NOT use legal jargon or ask about document "
        "structure the analyst may not know. End with: "
        "\"(Or type 'skip' to continue without this information.)\""
    )
    try:
        return complete(prompt, max_tokens=120, temperature=0.2).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to generate clarification question: %s", exc)
        return (
            f"I found {found_str} but couldn't locate {missing_str} in the document. "
            "Do you know which section or page these appear on? "
            "(Or type 'skip' to continue without this information.)"
        )
