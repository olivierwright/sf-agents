"""Rich run tracer: captures full step-by-step execution details for debugging.

Unlike the audit JSONL (which is append-only, governance-grade, and stores only
hashes), the trace file stores the actual inputs, outputs, citations, LLM calls,
and timing for every step in a run. It is written atomically at run completion.

Trace files live in ``trace_logs/{run_id}.trace.json``.

Usage in the executor::

    tracer = RunTracer(run_id, cfg.trace_dir)
    tracer.set_plan(plan)
    # per step:
    tracer.log_step_start(step_id, primitive, version, resolved_args)
    tracer.log_step_done(step_id, output, duration_ms)
    # optional LLM call (via thread-local interception):
    tracer.log_llm(step_id, primitive, prompt, system, response)
    # at run end:
    tracer.finalize(question, strategy, started_at_iso)
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..orchestrator.planner import Plan
from ..primitives.base import PrimitiveOutput

logger = logging.getLogger("sf_agents.run_tracer")

_MAX_PAYLOAD_PAGES = 5       # cap on pages stored in trace (full payloads are large)
_MAX_PROMPT_PREVIEW = 600    # chars kept from start of prompt
_MAX_PROMPT_TAIL    = 200    # chars kept from end of prompt
_MAX_RESP_PREVIEW   = 800    # chars kept from start of LLM response


@dataclass
class _LLMCall:
    seq: int
    prompt_chars: int
    prompt_preview: str
    system: Optional[str]
    response_chars: int
    response_preview: str
    parsed_ok: bool


@dataclass
class _StepTrace:
    step_id: str
    primitive: str
    version: str = ""
    input_args: dict[str, Any] = field(default_factory=dict)
    output_payload: Any = None
    confidence: float = 0.0
    citations: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    llm_calls: list[_LLMCall] = field(default_factory=list)
    _llm_seq: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "primitive": self.primitive,
            "version": self.version,
            "input_args": _safe_truncate_args(self.input_args),
            "output": {
                "payload": _safe_truncate_payload(self.output_payload),
                "confidence": round(self.confidence, 4),
                "citations": self.citations,
                "issues": self.issues,
            },
            "duration_ms": round(self.duration_ms, 1),
            "llm_calls": [_llm_call_dict(c) for c in self.llm_calls],
        }


def _llm_call_dict(c: _LLMCall) -> dict:
    return {
        "seq": c.seq,
        "prompt_chars": c.prompt_chars,
        "prompt_preview": c.prompt_preview,
        "system": c.system[:200] if c.system else None,
        "response_chars": c.response_chars,
        "response_preview": c.response_preview,
        "parsed_ok": c.parsed_ok,
    }


def _safe_truncate_args(args: dict) -> dict:
    """Truncate large arg values for the trace file."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, list) and len(v) > 10:
            out[k] = v[:5] + [f"... ({len(v) - 5} more items)"]
        elif isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + f"... ({len(v) - 500} more chars)"
        else:
            out[k] = v
    return out


def _safe_truncate_payload(payload: Any) -> Any:
    """Truncate large payload fields (e.g. pages list)."""
    if not isinstance(payload, dict):
        return payload
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k == "pages" and isinstance(v, list):
            out[k] = v[:_MAX_PAYLOAD_PAGES]
            if len(v) > _MAX_PAYLOAD_PAGES:
                out["_pages_truncated"] = f"{len(v)} total, showing first {_MAX_PAYLOAD_PAGES}"
        elif k == "rows" and isinstance(v, list) and len(v) > 20:
            out[k] = v[:20]
            out["_rows_truncated"] = f"{len(v)} total, showing first 20"
        elif isinstance(v, str) and len(v) > 1000:
            out[k] = v[:1000] + f"... ({len(v) - 1000} more chars)"
        else:
            out[k] = v
    return out


class RunTracer:
    """Accumulates execution data for one run and writes a trace file at completion."""

    def __init__(self, run_id: str, trace_dir: Path) -> None:
        self.run_id = run_id
        self._trace_dir = trace_dir
        self._lock = threading.Lock()
        self._steps: dict[str, _StepTrace] = {}
        self._step_order: list[str] = []
        self._plan: Optional[dict] = None
        self._started_at: Optional[str] = None
        self._finished_at: Optional[str] = None

    def set_plan(self, plan: Plan) -> None:
        with self._lock:
            self._plan = plan.as_dict()

    def log_step_start(
        self,
        step_id: str,
        primitive: str,
        version: str,
        input_args: dict[str, Any],
    ) -> None:
        with self._lock:
            self._steps[step_id] = _StepTrace(
                step_id=step_id,
                primitive=primitive,
                version=version,
                input_args=dict(input_args),
            )
            if step_id not in self._step_order:
                self._step_order.append(step_id)

    def log_step_done(
        self,
        step_id: str,
        output: PrimitiveOutput,
        duration_ms: float,
    ) -> None:
        with self._lock:
            st = self._steps.get(step_id)
            if st is None:
                st = _StepTrace(step_id=step_id, primitive="unknown")
                self._steps[step_id] = st
                self._step_order.append(step_id)
            st.output_payload = output.payload
            st.confidence = output.confidence
            st.citations = [
                {"source": c.source, "location": c.location, "excerpt": c.excerpt[:200]}
                for c in output.citations
            ]
            st.issues = list(output.issues)
            st.duration_ms = duration_ms

    def log_llm(
        self,
        step_id: str,
        primitive: str,
        prompt: str,
        system: Optional[str],
        response: Any,
        parsed_ok: bool = True,
    ) -> None:
        with self._lock:
            st = self._steps.get(step_id)
            if st is None:
                st = _StepTrace(step_id=step_id, primitive=primitive)
                self._steps[step_id] = st
                self._step_order.append(step_id)
            st._llm_seq += 1
            preview_start = prompt[:_MAX_PROMPT_PREVIEW]
            preview_tail = prompt[-_MAX_PROMPT_TAIL:] if len(prompt) > _MAX_PROMPT_PREVIEW + _MAX_PROMPT_TAIL else ""
            prompt_preview = preview_start + (f"\n...[{len(prompt) - _MAX_PROMPT_PREVIEW - _MAX_PROMPT_TAIL} chars skipped]...\n" + preview_tail if preview_tail else "")
            resp_str = json.dumps(response) if not isinstance(response, str) else response
            st.llm_calls.append(_LLMCall(
                seq=st._llm_seq,
                prompt_chars=len(prompt),
                prompt_preview=prompt_preview,
                system=system,
                response_chars=len(resp_str),
                response_preview=resp_str[:_MAX_RESP_PREVIEW],
                parsed_ok=parsed_ok,
            ))

    def finalize(self, question: str, strategy: str, started_at: Optional[str] = None) -> Optional[str]:
        """Write the trace file and return its path (or None on failure)."""
        self._finished_at = datetime.now(timezone.utc).isoformat()
        self._started_at = started_at or self._finished_at

        # Compute total duration
        try:
            t0 = datetime.fromisoformat(self._started_at.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(self._finished_at.replace("Z", "+00:00"))
            duration_ms = (t1 - t0).total_seconds() * 1000
        except Exception:
            duration_ms = 0.0

        trace: dict[str, Any] = {
            "run_id": self.run_id,
            "question": question,
            "strategy": strategy,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "duration_ms": round(duration_ms, 1),
            "plan": self._plan,
            "steps": [self._steps[sid].as_dict() for sid in self._step_order if sid in self._steps],
        }

        try:
            self._trace_dir.mkdir(parents=True, exist_ok=True)
            path = self._trace_dir / f"{self.run_id}.trace.json"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(trace, fh, indent=2, default=str)
            logger.info("trace written: %s", path)
            return str(path)
        except Exception as exc:
            logger.warning("could not write trace for run %s: %s", self.run_id, exc)
            return None
