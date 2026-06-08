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

# Maps lod.* primitive names to (line_number, display_label) for LOD_AGENT events.
_LOD_LINE_MAP: dict[str, tuple[int, str]] = {
    "lod.credit": (1, "Credit Agent"),
    "lod.risk":   (2, "Risk Agent"),
    "lod.audit":  (3, "Audit Agent"),
}

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
                if step.primitive in _LOD_LINE_MAP:
                    line, label = _LOD_LINE_MAP[step.primitive]
                    self._emit(
                        EventType.LOD_AGENT_STARTED,
                        {"step_id": step.step_id, "agent": step.primitive,
                         "line": line, "label": label},
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
                if step.primitive in _LOD_LINE_MAP and isinstance(output.payload, dict):
                    line, label = _LOD_LINE_MAP[step.primitive]
                    self._emit(
                        EventType.LOD_AGENT_FINISHED,
                        {"step_id": step.step_id, "agent": step.primitive,
                         "line": line, "label": label, "output": output.payload},
                    )

                # Never trigger HITL when the extractor has autonomously certified
                # that the data is genuinely absent — it already exhausted all
                # strategies and the synthesizer will explain the gap.
                absence_certified = (
                    isinstance(output.payload, dict)
                    and bool(output.payload.get("absence_certified", False))
                )
                if absence_certified:
                    self._emit(
                        EventType.STEP_ABSENCE_CERTIFIED,
                        {
                            "step_id": step.step_id,
                            "primitive": step.primitive,
                            "absence_explanation": (
                                output.payload.get("absence_explanation", "")
                                if isinstance(output.payload, dict) else ""
                            ),
                            "gap_summary": (
                                output.payload.get("gap_summary", "")
                                if isinstance(output.payload, dict) else ""
                            ),
                            "strategies_tried": (
                                output.payload.get("strategies_tried", [])
                                if isinstance(output.payload, dict) else []
                            ),
                        },
                    )

                # Trigger HITL / review for any output below the confidence floor,
                # unless the extractor certified absence (those are intentional gaps).
                is_below_floor = (
                    output.confidence < self._config.confidence_floor
                    and not absence_certified
                )
                if is_below_floor:
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
                        # Decode numbered choices into actionable hint text before
                        # deciding whether to retry (e.g. "2" for waterfall → page range)
                        decoded_answer = _decode_answer(step.primitive, answer)
                        helped = not _user_cant_help(answer, primitive=step.primitive)
                        confidence_before = output.confidence
                        retry_output: Optional[PrimitiveOutput] = None

                        if helped:
                            # Retry the step with the analyst's hint injected
                            try:
                                hint_args = dict(args)
                                hint_args["context_hint"] = decoded_answer
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
                                        confidence_before,
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
    "doesn't matter", "dont care", "don't care", "continue", "proceed",
)

# Maps (primitive, numbered_choice) → decoded hint text for retry.
# When an analyst picks a numbered option that encodes a page-range or
# section name, we convert it to an actionable string before the retry.
_CHOICE_HINTS: dict[tuple[str, str], str] = {
    ("extractor.waterfall", "2"): "Section 5 (Credit Structure), pages 100-180",
}


def _decode_answer(primitive: str, answer: str) -> str:
    """Expand a bare numbered choice into an actionable hint for retry.

    Returns the original answer unchanged if no expansion is registered.
    """
    stripped = answer.strip()
    return _CHOICE_HINTS.get((primitive, stripped), answer)


def _user_cant_help(answer: str, primitive: str = "") -> bool:
    """Return True when the analyst's answer signals they cannot provide useful guidance.

    Handles the numbered-choice format:
      option "1" always means continue/skip (non-actionable).
      option "2" meaning is primitive-dependent:
        - definitions: "use regulatory definition" → non-actionable for retry.
        - waterfall: "search Section 5, pages 100-180" → actionable.
      option "3" bare (no extra text): treat as skip.
    """
    stripped = answer.strip()
    lowered = stripped.lower()

    if stripped == "1":
        return True

    # "2" is primitive-dependent: if we have a registered hint for it, it's actionable
    if stripped == "2":
        return (primitive, "2") not in _CHOICE_HINTS

    # bare "3" with no extra detail — skip
    if stripped == "3":
        return True

    return not stripped or any(p in lowered for p in _CANT_HELP_PHRASES)


def _generate_clarification_question(
    step_id: str,
    primitive: str,
    output: PrimitiveOutput,
    plan_context: str,
) -> str:
    """Generate a numbered-choice clarification for the analyst.

    This fires only on COMPLETE failure (confidence == 0, nothing found).
    The question presents 3 concrete numbered options the analyst can action
    immediately without needing to know the document's internal structure.
    """
    payload = output.payload or {}
    missing_items: list[str] = []
    primitive_type = ""

    if isinstance(payload, dict):
        # Work out what was being extracted
        if "definitions" in payload:
            primitive_type = "definitions"
        elif "waterfall_steps" in payload:
            primitive_type = "waterfall"
        elif "covenants" in payload:
            primitive_type = "covenants"

    for issue in output.issues:
        for marker in ("No definition extracted for:", "LLM extraction failed:"):
            if marker in issue:
                raw = issue.replace(marker, "").strip().rstrip(".")
                missing_items.extend(t.strip() for t in raw.split(",") if t.strip())

    missing_str = ", ".join(missing_items[:5]) if missing_items else "the requested items"

    # Build domain-aware numbered options based on primitive type
    if primitive_type == "definitions":
        prompt = (
            "You are a structured finance assistant. An automated extraction step "
            f"({step_id}) searched the prospectus and found NOTHING for: {missing_str}.\n\n"
            "Generate a short message (4–6 lines) telling the analyst the extraction "
            "found nothing, then offer exactly 3 numbered choices:\n"
            "  1. Continue without these terms (use what was found elsewhere)\n"
            "  2. These terms may follow a regulatory definition (e.g. EBA/CRR) rather "
            "than being defined in the prospectus itself — treat them as regulatory references\n"
            "  3. Provide a specific page number or section name to search instead\n\n"
            "End with: 'Type 1, 2, or 3 (or paste a page number / section name):'"
        )
    elif primitive_type == "waterfall":
        prompt = (
            "You are a structured finance assistant. An automated step "
            f"({step_id}) could not locate the Priority of Payments waterfall.\n\n"
            "Generate a short message (4–6 lines) then offer 3 numbered choices:\n"
            "  1. Skip the waterfall extraction and continue with other data\n"
            "  2. The waterfall is in Section 5 (Credit Structure) — search pages 100-180\n"
            "  3. Provide the exact page or section name where the waterfall appears\n\n"
            "End with: 'Type 1, 2, or 3 (or paste a page number / section name):'"
        )
    else:
        prompt = (
            "You are a structured finance assistant. An automated step "
            f"({step_id}) found nothing for: {missing_str}.\n\n"
            "Generate a short message (4–6 lines) then offer 3 numbered choices:\n"
            "  1. Skip these items and continue with other extracted data\n"
            "  2. These items may be defined by regulatory cross-reference, not in the document\n"
            "  3. Provide the page or section where these items can be found\n\n"
            "End with: 'Type 1, 2, or 3 (or paste a page number / section name):'"
        )

    try:
        return complete(prompt, max_tokens=200, temperature=0.2).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to generate clarification question: %s", exc)
        return (
            f"I searched the document but found nothing for: {missing_str}.\n\n"
            "How should I proceed?\n"
            "  1. Continue without these items\n"
            "  2. Treat them as regulatory definitions (EBA/CRR)\n"
            "  3. Provide the page or section name where they appear\n\n"
            "Type 1, 2, or 3 (or paste a page number / section name):"
        )
