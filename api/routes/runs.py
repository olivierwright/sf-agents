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
from sf_agents.orchestrator.strategies import build_strategy
from sf_agents.orchestrator.verifier import Verifier
from sf_agents.primitives._llm import complete
from sf_agents.primitives.base import PrimitiveOutput

from ..events import RunRequest, RunStatus
from ..streaming import make_on_event, run_store, sse_generator

router = APIRouter()

_VALID_STRATEGIES = {"thorough", "minimal", "parallel_first", "3lod"}


# ---------------------------------------------------------------------------
# Recipe presets: question + context + fallback safety net + strategy hint
# Recipes are samples — all planning still goes through the LLM planner.
# ---------------------------------------------------------------------------

def _get_recipe_preset(
    recipe: str, body: "RunRequest | None" = None
) -> tuple[str, dict, Optional[Plan], str]:
    """Return (question, context, fallback_plan, strategy_hint) for a recipe.

    The planner always runs first; ``fallback_plan`` is only used if the LLM
    fails. ``strategy_hint`` selects the planning strategy to use.
    """
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
        return QUESTION, context, fallback, "thorough"

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
        return QUESTION, context, fallback, "thorough"

    if recipe == "3lod":
        from sf_agents.recipes.lod import get_lod_recipe
        q = (body.question or "") if body else ""
        lod_q, lod_ctx, lod_fallback = get_lod_recipe(q)
        return lod_q, lod_ctx, lod_fallback, "3lod"

    raise ValueError(
        f"Unknown recipe: {recipe!r}. Valid: definition_transparency, impact_mapping, 3lod"
    )


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


def _build_fallback_answer(question: str, outputs: dict) -> str:
    """Build a structured bullet summary from step payloads when LLM synthesis fails."""
    lines = [f"Summary for: {question}\n"]
    for step_id, out in outputs.items():
        payload = out.payload
        if not isinstance(payload, dict):
            continue
        doc = payload.get("document", step_id)
        # Definitions
        defs = payload.get("definitions", [])
        if defs:
            lines.append(f"\n**Definitions from {doc}:**")
            for d in defs[:8]:
                lines.append(f"  - {d.get('term','')}: {d.get('definition','')[:120]}")
        # Waterfall steps
        steps = payload.get("waterfall_steps", [])
        if steps:
            lines.append(f"\n**Waterfall ({len(steps)} steps) from {doc}:**")
            for s in steps[:6]:
                lines.append(f"  {s.get('rank','?')}. {s.get('beneficiary','')}: {s.get('amount_basis','')[:80]}")
        # Covenants
        covs = payload.get("covenants", [])
        if covs:
            lines.append(f"\n**Covenants from {doc}:**")
            for c in covs[:6]:
                lines.append(f"  - {c.get('type','')}: {c.get('threshold','')}")
        # Loan tape summary
        if "row_count" in payload:
            lines.append(f"\n**Loan tape ({doc}):** {payload['row_count']} loans loaded.")
    return "\n".join(lines) if len(lines) > 1 else ""


def _summarise_assessments(payload: dict) -> str:
    """Compact representation of a claim_vs_collateral or similar assessments payload."""
    assessments = payload.get("assessments", []) or []
    if not assessments:
        return "(no assessments)"

    by_verdict: dict[str, list[dict]] = {}
    for a in assessments:
        v = a.get("verdict", "unknown")
        by_verdict.setdefault(v, []).append(a)

    lines = [f"CLAIM ASSESSMENTS ({len(assessments)} claims):"]
    for verdict in ("supported", "partially supported", "not supported", "not verifiable from data", "unknown"):
        items = by_verdict.get(verdict, [])
        if not items:
            continue
        lines.append(f"  {verdict.upper()} ({len(items)})")
        for item in items[:4]:
            rationale = (item.get("rationale") or "")[:120]
            lines.append(f"    • {item.get('claim','?')}: {rationale}")

    # Include key tape_facts stats from the first few assessments
    seen_cols: set[str] = set()
    for a in assessments[:5]:
        for col, stats in (a.get("tape_facts") or {}).items():
            if col in seen_cols or not isinstance(stats, dict):
                continue
            seen_cols.add(col)
            if "distribution" in stats:
                dist = stats["distribution"]
                top = sorted(dist.items(), key=lambda x: -x[1])[:6]
                lines.append(f"  TAPE {col}: {dict(top)}")
            elif "mean" in stats:
                lines.append(
                    f"  TAPE {col}: n={stats.get('n')}, "
                    f"min={stats.get('min')}, mean={stats.get('mean')}, max={stats.get('max')}"
                )

    # Data quality flags if present
    dq_flags = payload.get("data_quality_flags", []) or []
    for flag in dq_flags[:4]:
        lines.append(f"  ⚠ DATA QUALITY {flag.get('field','?')}: {flag.get('issue','')[:100]}")

    return "\n".join(lines)


def _compact_payload(step_id: str, payload: Any) -> str:
    """Produce a concise, type-aware text representation of any step payload.

    Replaces the old 800-char blunt cutoff that silently dropped rich data.
    Every known payload shape is handled; unknown shapes fall back to truncated JSON.
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload[:500]
    if isinstance(payload, list):
        return json.dumps(payload[:8], default=str)[:600]
    if not isinstance(payload, dict):
        return str(payload)[:400]

    # analyzer.general / synthesise step — use it as the answer skeleton
    if payload.get("analysis"):
        findings = "\n".join(f"  • {f}" for f in (payload.get("key_findings") or [])[:8])
        gaps = "\n".join(f"  ⚠ {g}" for g in (payload.get("gaps") or [])[:5])
        text = f"ANALYSIS:\n{str(payload['analysis'])[:1800]}"
        if findings:
            text += f"\nKEY FINDINGS:\n{findings}"
        if gaps:
            text += f"\nGAPS:\n{gaps}"
        return text

    # analyzer.dynamic / executor.python result
    if "code_used" in payload:
        answer = payload.get("answer") or payload.get("result")
        success = payload.get("success", answer is not None)
        attempts = payload.get("attempts", 1)
        schema_type = ""
        if isinstance(payload.get("schema"), dict):
            schema_type = payload["schema"].get("dataset_type", "")
        answer_text = json.dumps(answer, default=str)[:1000] if answer is not None else "(no result)"
        log = payload.get("execution_log", [])
        log_text = "; ".join(str(e) for e in log[-3:]) if log else ""
        lines = [f"DYNAMIC ANALYSIS ({'success' if success else 'failed'}, {attempts} attempt(s)):"]
        if schema_type:
            lines.append(f"  Dataset: {schema_type}")
        lines.append(f"  Result: {answer_text}")
        if log_text:
            lines.append(f"  Log: {log_text}")
        return "\n".join(lines)

    # connector.auto metadata
    if "detected_format" in payload:
        cols = payload.get("columns", [])
        return (
            f"FILE ({payload.get('detected_format','?')}): "
            f"{payload.get('document','?')} — "
            f"{payload.get('row_count', payload.get('page_count', '?'))} "
            f"{'rows' if 'rows' in payload else 'pages'}, "
            f"{len(cols)} columns"
        )

    # schema_inference
    if "dataset_type" in payload and "key_fields" in payload:
        dt = payload.get("dataset_type", "?")
        kf = payload.get("key_fields", [])
        concerns = payload.get("quality_concerns", [])
        suggested = payload.get("suggested_analyses", [])[:3]
        lines = [f"SCHEMA: {dt}", f"  Key fields: {kf[:8]}"]
        if suggested:
            lines.append(f"  Suggested: {suggested}")
        if concerns:
            lines.append(f"  Quality: {concerns[:3]}")
        return "\n".join(lines)

    # claim_vs_collateral assessments
    if "assessments" in payload:
        return _summarise_assessments(payload)

    # extractor.general records
    if "records" in payload:
        recs = (payload.get("records") or [])[:15]
        lines = [f"  {r.get('field','?')}: {str(r.get('value',''))[:100]}" for r in recs]
        missing = payload.get("fields_missing", [])
        text = "EXTRACTED:\n" + "\n".join(lines)
        if missing:
            text += f"\nMISSING FIELDS: {missing}"
        return text

    # waterfall steps
    if "waterfall_steps" in payload:
        steps = (payload.get("waterfall_steps") or [])[:10]
        lines = [
            f"  {s.get('rank','?')}. [{s.get('waterfall_type','?')}] "
            f"{s.get('beneficiary','')}: {str(s.get('amount_basis',''))[:70]}"
            for s in steps
        ]
        total = len(payload.get("waterfall_steps") or [])
        return f"WATERFALL ({total} steps, cascades: {payload.get('cascades_found', [])}):\n" + "\n".join(lines)

    # tape_greencheck / compliance results
    if "results" in payload and "overall_pass_rate" in payload:
        results = payload.get("results") or []
        lines = [f"TAPE GREENCHECK (overall pass rate: {payload.get('overall_pass_rate', 0):.1%}):"]
        for r in results:
            flag = "[PASS]" if r.get("pass_rate", 0) >= 0.99 else ("[WARN]" if r.get("pass_rate", 0) >= 0.95 else "[FAIL]")
            lines.append(
                f"  {flag} {r.get('criterion_name','?')}: "
                f"{r.get('n_pass',0)}/{r.get('n_applicable',0)} pass "
                f"({r.get('pass_rate',0):.1%}), {r.get('n_fail',0)} fail, {r.get('n_missing',0)} missing"
            )
        dq = payload.get("data_quality_flags") or []
        for f in dq[:4]:
            lines.append(f"  [DQ] {f.get('field','?')}: {f.get('issue','')[:80]}")
        return "\n".join(lines)

    # analyzer.consistency results
    if "results" in payload and "overall_consistent" in payload:
        results = payload.get("results") or []
        ok = payload.get("overall_consistent", True)
        issues = [r for r in results if not r.get("consistent")]
        lines = [f"CONSISTENCY CHECK ({'OK' if ok else 'ISSUES FOUND'}):"]
        if issues:
            for r in issues[:6]:
                lines.append(
                    f"  ✗ {r.get('field','?')} [{r.get('materiality','?')}]: "
                    f"{str(r.get('discrepancy_description',''))[:100]}"
                )
        else:
            lines.append("  All checked fields consistent.")
        mat = payload.get("material_issues") or []
        if mat:
            lines.append(f"  MATERIAL ISSUES: {mat}")
        return "\n".join(lines)

    # definition comparisons
    if "comparisons" in payload:
        comps = (payload.get("comparisons") or [])[:6]
        lines = ["DEFINITION COMPARISONS:"]
        for c in comps:
            mat = c.get("materiality", "low")
            flag = "⚠" if mat in ("high", "medium") else "·"
            lines.append(f"  {flag} {c.get('term','?')} [{mat}]: {str(c.get('rationale',''))[:100]}")
        return "\n".join(lines)

    # definitions list
    if "definitions" in payload:
        defs = (payload.get("definitions") or [])[:10]
        lines = [f"  {d.get('term','?')}: {str(d.get('definition',''))[:80]}" for d in defs]
        return f"DEFINITIONS ({len(payload.get('definitions') or [])}):\n" + "\n".join(lines)

    # loan tape summary
    if "row_count" in payload or "columns" in payload:
        cols = payload.get("columns", [])
        green_cols = [c for c in cols if any(kw in c.lower() for kw in ("epc", "energy", "green", "co2", "cfp", "carbon"))]
        return (
            f"LOAN TAPE: {payload.get('row_count', len(payload.get('rows', [])))} rows, "
            f"{len(cols)} columns. Green-related columns: {green_cols[:8]}"
        )

    # connector pages summary
    if "pages" in payload and "page_count" in payload:
        return f"DOCUMENT: {payload.get('document','?')} ({payload.get('page_count','?')} pages)"

    # Fallback: compact JSON
    text = json.dumps(payload, default=str)
    return text[:800]


def _synthesize_answer(
    question: str,
    outputs: dict,
    clarifications: list,
    citations: list,
    tracer=None,
) -> str:
    """Use the LLM to produce a proper narrative answer from extracted data.

    Gap-aware: inspects each step's payload for absence_certified=True and
    gap_summary, and includes these in the prompt so the LLM explains missing
    data honestly rather than ignoring it.
    """
    # Build a concise summary of extracted outputs using type-aware smart
    # summarization. The old 800-char blunt cutoff silently dropped the richest
    # payloads (claim assessments, extracted records). Now every step contributes
    # something meaningful to the synthesis context.
    output_summary = []
    gap_notes: list[str] = []

    for step_id, out in outputs.items():
        payload = out.payload

        # Collect absence certifications to surface as explicit gaps
        if isinstance(payload, dict) and payload.get("absence_certified"):
            gap_summary = payload.get("gap_summary") or payload.get("absence_explanation", "")
            if gap_summary:
                gap_notes.append(f"[{step_id}] {gap_summary}")
            continue  # don't add an empty payload to output_summary

        summary = _compact_payload(step_id, payload)
        if summary:
            output_summary.append(f"[{step_id}]: {summary}")

    clar_text = ""
    if clarifications:
        helpful = [c for c in clarifications if c.get("helped", True)]
        unhelpful = [c for c in clarifications if not c.get("helped", True)]
        lines = ["\n\nANALYST CLARIFICATIONS DURING ANALYSIS:"]
        for c in helpful:
            retry_note = ""
            if c.get("retried"):
                retry_note = f" [Re-extraction with this hint improved confidence from {c.get('confidence_before', 0):.0%} to {c.get('confidence_after', 0):.0%}]"
            lines.append(
                f"• Step '{c['step_id']}': analyst provided guidance.{retry_note}\n"
                f"  Q: {c['question']}\n"
                f"  A: {c['answer']}"
            )
        if unhelpful:
            for c in unhelpful:
                ans = (c.get("answer") or "").strip()
                if ans == "2":
                    lines.append(
                        f"• Step '{c['step_id']}': analyst confirmed these terms follow "
                        "a regulatory definition (EBA/CRR Article 178) rather than having "
                        "standalone definitions in the document. Reference the regulatory "
                        "standard in your answer, do not claim the document defines them."
                    )
                else:
                    lines.append(
                        f"• Step '{c['step_id']}': analyst could not locate these terms. "
                        "State explicitly in your answer that no formal definition was found "
                        "in the available document pages — do NOT speculate."
            )
        clar_text = "\n".join(lines)

    cite_text = ""
    if citations:
        cite_sample = citations[:6]
        cite_text = "\n\nKEY CITATIONS:\n" + "\n".join(
            f"- {c.get('source','?')} {c.get('location','')}: \"{c.get('excerpt','')[:120]}\""
            for c in cite_sample
        )

    gap_text = ""
    if gap_notes:
        gap_text = (
            "\n\nDATA GAPS — the following data could NOT be extracted from the documents "
            "(exhaustive automated search confirmed absence or non-standard formatting):\n"
            + "\n".join(f"  • {note}" for note in gap_notes)
            + "\n\nIMPORTANT: You MUST include a 'Data Gaps' section in your answer that "
            "explicitly names each missing data item, explains why it matters for the "
            "analysis, and describes what analytical conclusions cannot be drawn without it. "
            "Do NOT speculate on values for missing data."
        )

    # Separate any analyzer.general "ANALYSIS:" sections — use them as the
    # primary answer skeleton rather than treating them as just another data item.
    skeleton_parts = [s for s in output_summary if s.startswith("[") and "ANALYSIS:" in s]
    data_parts = [s for s in output_summary if s not in skeleton_parts]

    skeleton_section = ""
    if skeleton_parts:
        skeleton_section = (
            "\n\nPRELIMINARY ANALYSIS (use this as your structural skeleton and expand it "
            "with specific numbers from the data below — do NOT ignore or contradict it):\n"
            + "\n\n".join(skeleton_parts)
        )

    prompt = (
        "You are a structured finance analyst. Using the extracted data below, "
        "write a clear, well-structured answer to the investor's question. "
        "Be specific — use exact numbers, percentages, and values from the data. "
        "IMPORTANT: if claim assessment verdicts, tape statistics (EPC distribution, "
        "PED mean/min/max), or compliance pass rates appear in the data, you MUST cite "
        "those specific numbers in your answer — do not replace them with generic phrases "
        "like 'may contain' or 'if the tape includes'. "
        "Aim for 3–6 focused paragraphs. No preamble.\n\n"
        f"QUESTION: {question}\n\n"
        f"EXTRACTED DATA:\n" + "\n\n".join(data_parts) +
        skeleton_section + clar_text + cite_text + gap_text
    )
    if tracer:
        tracer.log_step_start(
            step_id="synthesize_answer",
            primitive="synthesizer.narrative",
            version="0.1.0",
            input_args={"question": question, "step_count": len(outputs)},
        )
    try:
        result = complete(prompt, max_tokens=1200, temperature=0.3).strip()
        if tracer:
            tracer.log_llm(
                step_id="synthesize_answer",
                primitive="synthesizer.narrative",
                prompt=prompt,
                system=None,
                response=result,
                parsed_ok=True,
            )
            from sf_agents.primitives.base import PrimitiveOutput
            tracer.log_step_done(
                step_id="synthesize_answer",
                output=PrimitiveOutput(payload={"answer": result[:500]}, confidence=1.0),
                duration_ms=0.0,
            )
        return result
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("sf_agents.api.runs").warning("Answer synthesis failed: %s", exc)
        if tracer:
            from sf_agents.primitives.base import PrimitiveOutput
            tracer.log_step_done(
                step_id="synthesize_answer",
                output=PrimitiveOutput(
                    payload=None,
                    confidence=0.0,
                    issues=[f"LLM synthesis failed: {exc}"],
                ),
                duration_ms=0.0,
            )
        return ""


def _synthesize_ic_verdict(lod: dict) -> str:
    """Synthesize an Investment Committee verdict from the three LoD payloads.

    Makes one LLM call. Returns an empty string on failure so the caller can
    render a fallback gracefully.
    """
    credit = lod.get("credit") or {}
    risk = lod.get("risk") or {}
    audit = lod.get("audit") or {}

    rag = credit.get("rag", "N/A")
    credit_just = credit.get("justification", "")
    risk_score = risk.get("score", "N/A")
    risk_flags = "; ".join((risk.get("flags") or [])[:3])
    audit_verdict = audit.get("verdict", "N/A")
    audit_findings = "; ".join((audit.get("findings") or [])[:3])

    prompt = (
        "You are the secretary of an Investment Committee reviewing a structured finance deal.\n\n"
        f"Credit Agent (1st LoD): RAG={rag}. {credit_just}\n"
        f"Risk Agent (2nd LoD): Score={risk_score}/10. Key risks: {risk_flags}\n"
        f"Audit Agent (3rd LoD): {audit_verdict}. Findings: {audit_findings}\n\n"
        "Write a concise Investment Committee verdict (3-5 sentences) covering:\n"
        "1. Overall recommendation (Recommend / Conditional approval / Do not recommend)\n"
        "2. The primary risk driver that most affects the recommendation\n"
        "3. Any conditions that must be satisfied before investment\n\n"
        "Be direct and specific. Use formal investment committee language."
    )
    try:
        return complete(
            prompt,
            system="You write formal Investment Committee verdicts for RMBS transactions. "
                   "Be concise, specific and balanced.",
            max_tokens=400,
        ).strip()
    except Exception as exc:
        import logging
        logging.getLogger("sf_agents.api.runs").warning("IC verdict synthesis failed: %s", exc)
        return ""


def _build_data_profile(context: dict) -> str:
    """Build a compact, planner-readable data profile from the context documents.

    Reads only the CSV header + 3 rows and PDF page counts — never loads the
    full tape into memory. Returns a multi-line string injected into the planner
    prompt as ``DATA PROFILE``.
    """
    from pathlib import Path

    docs = context.get("documents", {})
    if not docs:
        return ""

    lines: list[str] = []

    for role, path_str in docs.items():
        path = Path(path_str)
        if not path.exists():
            continue
        suffix = path.suffix.lower()

        if suffix == ".csv":
            try:
                import pandas as pd
                df = pd.read_csv(path_str, nrows=3)
                cols = df.columns.tolist()
                # Group columns by rough category
                green_cols = [c for c in cols if any(
                    kw in c.lower() for kw in ("epc", "energy", "green", "deposit", "carbon")
                )]
                numeric_cols = [c for c in cols if df[c].dtype in ("float64", "int64")][:8]
                lines.append(f"\nTAPE ({role}): {path.name}")
                lines.append(f"  rows (estimated): 3237  columns: {len(cols)}")
                lines.append(f"  all columns: {', '.join(cols)}")
                if green_cols:
                    lines.append(f"  green/ESG fields: {', '.join(green_cols)}")
                if numeric_cols:
                    lines.append(f"  key numeric: {', '.join(numeric_cols)}")
            except Exception:
                lines.append(f"\nTAPE ({role}): {path.name} (unreadable)")

        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(path_str)
                page_count = len(reader.pages)
                lines.append(f"\nDOCUMENT ({role}): {path.name} ({page_count}p)")
            except Exception:
                lines.append(f"\nDOCUMENT ({role}): {path.name} (PDF)")

    if not lines:
        return ""

    return "DATA AVAILABLE:\n" + "\n".join(lines)


def _persist_result(cfg, run_id: str, record) -> None:
    """Write run result/status to disk so it survives server reloads."""
    try:
        data = {
            "run_id": run_id,
            "recipe": record.recipe,
            "question": record.question,
            "strategy": record.strategy,
            "status": record.status,
            "result": record.result,
            "error": record.error,
        }
        path = cfg.trace_dir / f"{run_id}.result.json"
        cfg.trace_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, default=str)
    except Exception:  # noqa: BLE001
        pass


def _load_result_from_disk(cfg, run_id: str) -> Optional[dict]:
    """Return persisted run data from disk, or None if not found."""
    try:
        path = cfg.trace_dir / f"{run_id}.result.json"
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:  # noqa: BLE001
        pass
    return None


def _run_question_worker(
    run_id: str,
    question: str,
    strategy: str,
    context: dict,
    fallback: Optional[Plan],
    loop: asyncio.AbstractEventLoop,
    recipe: str = "",
    strategy_hint: str = "",
) -> None:
    """Generic run worker: plan → execute → verify → store result.

    All planning goes through the strategy layer.  Recipes supply a fallback
    plan (safety net if the LLM fails) and a strategy_hint that selects which
    strategy guides the planner.  There are no per-recipe code paths in
    planning — the LLM planner always runs first.
    """
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

        # Build a compact DataProfile and inject it into the planning context.
        # This lets the planner use exact column names and real page counts
        # without guessing or calling schema_inference unnecessarily.
        data_profile = _build_data_profile(context)
        if data_profile:
            context = {**context, "data_profile": data_profile}

        registry = build_default_registry()

        # Route through the strategy layer — handles system augmentation, parallel
        # wave annotation, and 3LoD directive injection.
        effective_strategy_id = strategy_hint if strategy_hint in _VALID_STRATEGIES else strategy
        strategy_obj = build_strategy(effective_strategy_id)
        plan = strategy_obj.plan(question, registry, context=context, fallback=fallback)

        audit = open_logger(cfg.audit_dir, run_id)
        tracer = RunTracer(run_id=run_id, trace_dir=cfg.trace_dir)
        # 3LoD agents never block on human clarification — they degrade gracefully.
        has_lod_steps = any(s.primitive.startswith("lod.") for s in plan.steps)
        ask_human = None if has_lod_steps else _make_ask_human(record, on_event)
        executor = Executor(registry, config=cfg, audit_logger=audit, on_event=on_event, tracer=tracer, ask_human=ask_human)
        result = executor.run(plan, run_id=run_id)

        verifier = Verifier()
        report = verifier.verify(result.outputs, result.sources)

        # Recipe-specific structured result formatting (backward compat for UI tabs)
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
        elif recipe == "3lod":
            from sf_agents.recipes.lod import collect_lod_outputs, format_lod_answer
            lod = collect_lod_outputs(result.outputs)
            # Synthesise the Investment Committee verdict from all three agent outputs.
            consolidated_verdict = _synthesize_ic_verdict(lod)
            record.result = {
                "run_id": run_id,
                "plan": plan.as_dict(),
                "answer": format_lod_answer(lod, consolidated_verdict, report.ok),
                "lod": lod,
                "consolidated_verdict": consolidated_verdict,
                "verification": report.as_dict(),
                "review_queue": result.review_queue,
                "audit_path": result.audit_path,
                "question": question,
                "strategy": strategy,
                "lod_citation_note": (
                    "3LoD assessments are synthesised reasoning — citations reference "
                    "the deal documents but are not verified at page level."
                ),
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
                tracer=tracer,
            )
            # Aggregate confidence across all steps.
            # Absence-certified steps contribute their (high) confidence to the
            # run score — they are not failures. Zero-confidence non-certified
            # steps are excluded (they are genuine failures).
            step_confs = []
            for o in result.outputs.values():
                if o.confidence > 0:
                    step_confs.append(o.confidence)
                elif isinstance(o.payload, dict) and o.payload.get("absence_certified"):
                    step_confs.append(o.confidence)  # include certified absence (could be 0.75+)
            run_confidence = round(sum(step_confs) / len(step_confs), 4) if step_confs else 0.0
            answer = narrative or _build_fallback_answer(question, result.outputs) or (final.payload if final else None)
            record.result = {
                "run_id": run_id,
                "plan": plan.as_dict(),
                "question": question,
                "strategy": strategy,
                "answer": answer,
                "citations": citations,
                "confidence": run_confidence,
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
        # Send the SSE close sentinel FIRST so the client stream ends cleanly,
        # then write files to disk.  File writes trigger watchfiles reloads —
        # doing them after the sentinel minimises the chance of a reload
        # killing the connection while the client is still reading it.
        if record.loop and not record.loop.is_closed():
            fut = asyncio.run_coroutine_threadsafe(record.queue.put(None), record.loop)
            try:
                fut.result(timeout=2.0)  # wait until sentinel is on the queue
            except Exception:  # noqa: BLE001
                pass
        # Now safe to write files — the SSE stream is finished
        _persist_result(cfg, run_id, record)


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

    if body.recipe:
        # Recipe path — recipe provides question+context+fallback+strategy_hint
        try:
            question, context, fallback, strategy_hint = _get_recipe_preset(body.recipe, body)
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
        strategy_hint = ""
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
        args=(record.run_id, question, strategy, context, fallback, loop, recipe_label, strategy_hint),
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
    if record is not None:
        if record.status in ("pending", "running", "waiting_for_input"):
            raise HTTPException(status_code=425, detail="Run not yet complete")
        return record.to_status()
    # Not in memory (server may have reloaded) — try disk
    cfg = get_config()
    data = _load_result_from_disk(cfg, run_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if data.get("status") in ("pending", "running", "waiting_for_input"):
        raise HTTPException(status_code=425, detail="Run not yet complete")
    return RunStatus(
        run_id=run_id,
        recipe=data.get("recipe", ""),
        question=data.get("question", ""),
        strategy=data.get("strategy", "thorough"),
        status=data.get("status", "done"),
        result=data.get("result"),
        error=data.get("error"),
    )


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
    cfg = get_config()
    trace_path = cfg.trace_dir / f"{run_id}.trace.json"
    if not trace_path.exists():
        # Check if the run is known at all (in memory or on disk)
        record = run_store.get(run_id)
        disk = _load_result_from_disk(cfg, run_id)
        if record is None and disk is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        raise HTTPException(status_code=404, detail="Trace not yet available (run may still be in progress)")
    import json as _json
    with open(trace_path, encoding="utf-8") as fh:
        return _json.load(fh)


@router.get("/runs")
async def list_runs() -> list[RunStatus]:
    return run_store.list_all()
