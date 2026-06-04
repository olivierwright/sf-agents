"""Runs routes — POST /api/runs, GET /api/runs/{id}/stream, etc."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sf_agents.config import get_config
from sf_agents.governance.audit_logger import open_logger
from sf_agents.orchestrator.executor import Executor
from sf_agents.orchestrator.planner import Plan, Planner
from sf_agents.orchestrator.registry import build_default_registry
from sf_agents.orchestrator.verifier import Verifier
from sf_agents.primitives._llm import complete
from sf_agents.primitives.base import PrimitiveOutput

from ..events import RunRequest, RunStatus
from ..streaming import make_on_event, run_store, sse_generator

router = APIRouter()

_VALID_STRATEGIES = {"thorough", "minimal", "parallel_first"}


# ---------------------------------------------------------------------------
# Recipe shortcuts: map recipe id → (question, context_builder, fallback_builder)
# ---------------------------------------------------------------------------

def _get_recipe_context(recipe: str) -> tuple[str, dict, Optional[Plan]]:
    """Return (question, planner_context, fallback_plan) for a named recipe."""
    cfg = get_config()
    if recipe == "definition_transparency":
        from sf_agents.recipes.definition_transparency import (
            DEFAULT_TERMS,
            INVESTOR_REPORT_FILE,
            LOAN_TAPE_FILE,
            PROSPECTUS_FILE,
            QUESTION,
            build_fallback_plan,
        )
        prospectus_path = str(cfg.deal_file(PROSPECTUS_FILE))
        investor_report_path = str(cfg.deal_file(INVESTOR_REPORT_FILE))
        loan_tape_path = str(cfg.deal_file(LOAN_TAPE_FILE))
        terms = list(DEFAULT_TERMS)
        context: dict = {
            "documents": {
                "prospectus": prospectus_path,
                "investor_report": investor_report_path,
                "loan_tape": loan_tape_path,
            },
            "terms": terms,
        }
        fallback = build_fallback_plan(
            prospectus_path=prospectus_path,
            investor_report_path=investor_report_path,
            loan_tape_path=loan_tape_path,
            terms=terms,
        )
        return QUESTION, context, fallback

    if recipe == "impact_mapping":
        from sf_agents.recipes.impact_mapping import (
            DEFAULT_GREEN_TERMS,
            LOAN_TAPE_FILE,
            QUESTION,
            _CLAIM_DOCS,
            build_fallback_plan,
        )
        claim_doc_paths = {suffix: str(cfg.deal_file(file)) for suffix, file in _CLAIM_DOCS}
        loan_tape_path = str(cfg.deal_file(LOAN_TAPE_FILE))
        terms = list(DEFAULT_GREEN_TERMS)
        context = {
            "documents": {**claim_doc_paths, "loan_tape": loan_tape_path},
            "terms": terms,
        }
        fallback = build_fallback_plan(
            claim_doc_paths=claim_doc_paths,
            loan_tape_path=loan_tape_path,
            terms=terms,
        )
        return QUESTION, context, fallback

    raise ValueError(f"Unknown recipe: {recipe!r}. Valid: definition_transparency, impact_mapping")


# ---------------------------------------------------------------------------
# Generic background worker
# ---------------------------------------------------------------------------

def _augment_question(question: str, strategy: str) -> str:
    """Apply strategy-specific prompt augmentation to the question."""
    if strategy == "minimal":
        return (
            f"{question}\n\nPLANNING CONSTRAINT: Produce the MINIMUM number of steps "
            "that still produce a cited, verified answer. Prefer primitives that combine "
            "multiple functions. Omit any step whose output is not directly needed by a "
            "later step or the final answer. Do not include validation steps unless the "
            "question explicitly asks about data quality."
        )
    return question


def _annotate_parallel_waves(plan: Plan) -> Plan:
    """Annotate a plan's explanation with topological wave information."""
    from sf_agents.orchestrator.planner import _iter_refs

    by_id = {s.step_id: s for s in plan.steps}
    deps = {
        s.step_id: set(s.depends_on) | set(_iter_refs(s.args))
        for s in plan.steps
    }
    depth: dict[str, int] = {}

    def _depth(sid: str) -> int:
        if sid in depth:
            return depth[sid]
        depth[sid] = 0 if not deps[sid] else 1 + max(_depth(d) for d in deps[sid])
        return depth[sid]

    for sid in by_id:
        _depth(sid)

    groups: dict[int, list[str]] = {}
    for s in plan.steps:
        d = depth[s.step_id]
        groups.setdefault(d, []).append(s.step_id)

    wave_desc = "; ".join(
        f"wave {d}: [{', '.join(ids)}]" for d, ids in sorted(groups.items())
    )
    sorted_steps = sorted(plan.steps, key=lambda s: depth[s.step_id])
    new_explanation = f"{plan.explanation} | Parallel waves — {wave_desc}"
    return Plan(steps=sorted_steps, explanation=new_explanation, source=plan.source)


def _default_deal_context(cfg) -> dict:
    """Return document paths for the Green Lion deal as default context.

    Used when a free-form question is asked without explicit document paths.
    Falls back gracefully if any file is missing.

    Also includes file-format hints so the planner can select the right
    connector for each document (PDF → connector.prospectus / connector.pdf_document,
    CSV → connector.loan_tape). This prevents the planner from passing a PDF
    path to connector.remittance_file or connector.loan_tape.
    """
    from sf_agents.recipes.definition_transparency import (
        INVESTOR_REPORT_FILE,
        LOAN_TAPE_FILE,
        PROSPECTUS_FILE,
    )
    docs: dict = {}
    doc_formats: dict = {}
    for role, filename in [
        ("prospectus", PROSPECTUS_FILE),
        ("investor_report", INVESTOR_REPORT_FILE),
        ("loan_tape", LOAN_TAPE_FILE),
    ]:
        try:
            path = str(cfg.deal_file(filename))
            docs[role] = path
            doc_formats[role] = path.rsplit(".", 1)[-1].lower()
        except FileNotFoundError:
            pass

    if not docs:
        return {}

    return {
        "documents": docs,
        "document_formats": doc_formats,
        "connector_guide": (
            "prospectus → connector.prospectus; "
            "investor_report → connector.investor_report; "
            "loan_tape → connector.loan_tape (CSV); "
            "NO remittance CSV is available in this deal — do NOT use connector.remittance_file"
        ),
    }


def _make_ask_human(record, on_event) -> Any:
    """Return a blocking ask_human callback wired to the run record.

    When called from the executor background thread it:
    1. Emits a ``human_clarification_needed`` SSE event so the UI can display the question.
    2. Sets the record status to ``waiting_for_input`` and stores the pending question.
    3. Blocks (with a 5-minute timeout) until the frontend POSTs to ``/clarify``.
    4. Returns the human's answer string.
    """
    from sf_agents.orchestrator.events import EventType, RunEvent

    def _ask(step_id: str, primitive: str, output: PrimitiveOutput, question: str) -> str:
        record.status = "waiting_for_input"
        record.pending_clarification = {
            "step_id": step_id,
            "primitive": primitive,
            "confidence": output.confidence,
            "issues": list(output.issues),
            "question": question,
        }
        # Reset the event so we block on a fresh wait
        record.clarification_event.clear()
        record.clarification_answer = None
        # Emit to the SSE stream
        on_event(RunEvent(
            type=EventType.HUMAN_CLARIFICATION_NEEDED,
            payload=record.pending_clarification,
        ))
        # Block until the frontend submits an answer (or times out after 5 min)
        answered = record.clarification_event.wait(timeout=300)
        record.status = "running"
        record.pending_clarification = None
        if not answered or not record.clarification_answer:
            return "(no answer provided — treating result as-is)"
        return record.clarification_answer

    return _ask


def _synthesize_answer(
    question: str,
    outputs: dict,
    clarifications: list,
    citations: list,
) -> str:
    """Use the LLM to produce a proper narrative answer from extracted data."""
    # Build a concise summary of extracted outputs (skip huge payloads)
    output_summary = []
    for step_id, out in outputs.items():
        payload = out.payload
        if isinstance(payload, dict) and len(str(payload)) < 800:
            output_summary.append(f"[{step_id}]: {json.dumps(payload, default=str)[:600]}")
        elif isinstance(payload, list) and len(payload) <= 10:
            output_summary.append(f"[{step_id}]: {json.dumps(payload, default=str)[:600]}")
        elif isinstance(payload, str):
            output_summary.append(f"[{step_id}]: {payload[:400]}")

    clar_text = ""
    if clarifications:
        clar_text = "\n\nHUMAN CLARIFICATIONS PROVIDED DURING ANALYSIS:\n" + "\n".join(
            f"Q: {c['question']}\nA: {c['answer']}" for c in clarifications
        )

    cite_text = ""
    if citations:
        cite_sample = citations[:6]
        cite_text = "\n\nKEY CITATIONS:\n" + "\n".join(
            f"- {c.get('source','?')} {c.get('location','')}: \"{c.get('excerpt','')[:120]}\""
            for c in cite_sample
        )

    prompt = (
        "You are a structured finance analyst. Using the extracted data below, "
        "write a clear, well-structured answer to the investor's question. "
        "Be specific, use numbers where available, and cite sources where relevant. "
        "Aim for 3–5 focused paragraphs. Do not include preamble like 'Based on the analysis…'.\n\n"
        f"QUESTION: {question}\n\n"
        f"EXTRACTED DATA:\n" + "\n".join(output_summary) +
        clar_text + cite_text
    )
    try:
        return complete(prompt, max_tokens=1200, temperature=0.3).strip()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("sf_agents.api.runs").warning("Answer synthesis failed: %s", exc)
        return ""


def _run_question_worker(
    run_id: str,
    question: str,
    strategy: str,
    context: dict,
    fallback: Optional[Plan],
    loop: asyncio.AbstractEventLoop,
    recipe: str = "",
) -> None:
    """Generic run worker: plan → execute → verify → store result."""
    import time
    from datetime import datetime, timezone
    from sf_agents.governance.run_tracer import RunTracer

    record = run_store.get(run_id)
    assert record is not None
    record.loop = loop
    record.status = "running"
    on_event = make_on_event(record)  # create early so we can emit errors
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        cfg = get_config()

        # If no documents provided, default to the known deal files so any
        # free-form question about the deal has access to the source data.
        if not context.get("documents"):
            context = _default_deal_context(cfg)

        registry = build_default_registry()
        planner = Planner()

        effective_question = _augment_question(question, strategy)
        plan = planner.plan(effective_question, registry, context=context, fallback=fallback)

        if strategy == "parallel_first":
            plan = _annotate_parallel_waves(plan)

        audit = open_logger(cfg.audit_dir, run_id)
        tracer = RunTracer(run_id=run_id, trace_dir=cfg.trace_dir)
        ask_human = _make_ask_human(record, on_event)
        executor = Executor(registry, config=cfg, audit_logger=audit, on_event=on_event, tracer=tracer, ask_human=ask_human)
        result = executor.run(plan, run_id=run_id)

        verifier = Verifier()
        report = verifier.verify(result.outputs, result.sources)

        # Recipe-specific formatting for backward compat
        if recipe == "definition_transparency":
            from sf_agents.recipes.definition_transparency import format_answer
            final = result.final_output
            comparisons = (final.payload.get("comparisons", []) if final else []) or []
            validation = (
                result.outputs["tape_validate"].payload
                if "tape_validate" in result.outputs
                else {}
            )
            record.result = {
                "run_id": run_id,
                "plan": plan.as_dict(),
                "answer": format_answer(comparisons, report.ok),
                "comparisons": comparisons,
                "verification": report.as_dict(),
                "review_queue": result.review_queue,
                "validation": validation,
                "audit_path": result.audit_path,
                "question": question,
                "strategy": strategy,
            }
        elif recipe == "impact_mapping":
            from sf_agents.recipes.impact_mapping import _collect_assessments, format_answer
            assessments = _collect_assessments(result.outputs)
            record.result = {
                "run_id": run_id,
                "plan": plan.as_dict(),
                "answer": format_answer(assessments, report.ok),
                "assessments": assessments,
                "verification": report.as_dict(),
                "review_queue": result.review_queue,
                "audit_path": result.audit_path,
                "question": question,
                "strategy": strategy,
            }
        else:
            # Generic result format for free-form questions
            final = result.final_output
            citations = [
                {"source": c.source, "location": c.location, "excerpt": c.excerpt}
                for c in (final.citations if final else [])
            ]
            # Also collect citations from all steps for synthesis context
            all_citations = [
                {"source": c.source, "location": c.location, "excerpt": c.excerpt}
                for out in result.outputs.values()
                for c in out.citations
            ]
            # Synthesize a proper narrative answer instead of returning raw payload
            narrative = _synthesize_answer(
                question=question,
                outputs=result.outputs,
                clarifications=result.clarifications,
                citations=all_citations,
            )
            record.result = {
                "run_id": run_id,
                "plan": plan.as_dict(),
                "question": question,
                "strategy": strategy,
                "answer": narrative or (final.payload if final else None),
                "citations": citations,
                "confidence": final.confidence if final else None,
                "verification": report.as_dict(),
                "review_queue": result.review_queue,
                "clarifications": result.clarifications,
                "audit_path": result.audit_path,
            }

        trace_path = tracer.finalize(question=question, strategy=strategy, started_at=started_at)
        if trace_path and record.result:
            record.result["trace_path"] = trace_path
        record.status = "done"

    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("sf_agents.api.runs").exception("Run %s failed", run_id)
        try:
            tracer.finalize(question=question, strategy=strategy, started_at=started_at)
        except Exception:  # noqa: BLE001
            pass
        record.error = str(exc)
        record.status = "error"
        # Emit run_error so the SSE client transitions to the error phase
        from sf_agents.orchestrator.events import EventType, RunEvent
        try:
            on_event(RunEvent(type=EventType.RUN_ERROR, payload={"message": str(exc)}))
        except Exception:  # noqa: BLE001
            pass
    finally:
        if record.loop and not record.loop.is_closed():
            asyncio.run_coroutine_threadsafe(record.queue.put(None), record.loop)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/runs", status_code=202)
async def create_run(body: RunRequest) -> dict[str, str]:
    """Create a new analysis run.

    Two modes:
    - ``recipe``: shortcut to a predefined workflow (backward compat).
    - ``question``: free-form question with optional ``strategy`` and ``documents``.
    """
    strategy = body.strategy or "thorough"
    if strategy not in _VALID_STRATEGIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown strategy {strategy!r}. Valid: {sorted(_VALID_STRATEGIES)}",
        )

    if body.recipe and not body.question:
        # Recipe shortcut path
        try:
            question, context, fallback = _get_recipe_context(body.recipe)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        recipe_label = body.recipe
    elif body.question:
        # Free-form question path
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="'question' must not be blank.")
        documents = body.documents or {}
        context = {"documents": documents} if documents else {}
        fallback = None
        recipe_label = ""
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'recipe' (shortcut) or 'question' (free-form).",
        )

    record = run_store.create(
        recipe=recipe_label,
        question=question,
        strategy=strategy,
        run_id=body.run_id,
    )
    loop = asyncio.get_running_loop()
    thread = threading.Thread(
        target=_run_question_worker,
        args=(record.run_id, question, strategy, context, fallback, loop, recipe_label),
        daemon=True,
        name=f"sf-run-{record.run_id[:8]}",
    )
    thread.start()

    return {
        "run_id": record.run_id,
        "stream_url": f"/api/runs/{record.run_id}/stream",
        "result_url": f"/api/runs/{record.run_id}/result",
    }


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    record = run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    async def _gen():
        async for chunk in sse_generator(record):
            yield chunk

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class ClarifyRequest(BaseModel):
    answer: str


@router.post("/runs/{run_id}/clarify", status_code=200)
async def clarify_run(run_id: str, body: ClarifyRequest) -> dict[str, str]:
    """Submit a human answer to the pending clarification question.

    This unblocks the executor thread so the run can continue.
    """
    record = run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if record.status != "waiting_for_input":
        raise HTTPException(status_code=409, detail="Run is not waiting for clarification")
    record.clarification_answer = body.answer.strip() or "(no answer provided)"
    record.clarification_event.set()
    return {"status": "ok", "run_id": run_id}


@router.get("/runs/{run_id}/result")
async def get_result(run_id: str) -> RunStatus:
    record = run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if record.status in ("pending", "running", "waiting_for_input"):
        raise HTTPException(status_code=425, detail="Run not yet complete")
    return record.to_status()


@router.get("/runs/{run_id}/audit")
async def get_audit(run_id: str) -> list[dict[str, Any]]:
    """Return the raw audit log entries for a run."""
    record = run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    cfg = get_config()
    audit_path = cfg.audit_dir / f"{run_id}.audit.jsonl"
    if not audit_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(audit_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


@router.get("/runs/{run_id}/trace")
async def get_trace(run_id: str) -> dict[str, Any]:
    """Return the full run trace (step inputs, outputs, LLM calls)."""
    record = run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    cfg = get_config()
    trace_path = cfg.trace_dir / f"{run_id}.trace.json"
    if not trace_path.exists():
        raise HTTPException(status_code=404, detail="Trace not yet available (run may still be in progress)")

    import json as _json
    with open(trace_path, encoding="utf-8") as fh:
        return _json.load(fh)


@router.get("/runs")
async def list_runs() -> list[RunStatus]:
    return run_store.list_all()
