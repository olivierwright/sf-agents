"""General-purpose reasoning and analysis primitive.

Takes any upstream extracted data plus a question and produces a structured
analytical answer with citations and a gaps section.

This fills the reasoning gap between raw extraction and final synthesis:
many questions need intermediate analysis (e.g. "Is the OC ratio sufficient
to absorb a 10% default scenario?") that requires applying domain reasoning
to extracted numbers rather than just retrieving them.

The primitive is also gap-aware: if upstream steps have set
absence_certified=True, those gap_summary strings are explicitly
included in the prompt so the LLM reasons around missing data honestly
rather than hallucinating.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ...knowledge.loader import domain_preamble as _domain_preamble, gotchas_section as _gotchas_section, questions_section as _questions_section

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a senior structured-finance analyst. "
    "You reason carefully from the provided data. "
    "When data is missing or uncertain, you say so explicitly — you never fabricate numbers. "
    "Your analysis is structured, specific, and cites the data it references. "
    "Respond with a single JSON object only.\n\n"
    "=== STRUCTURED FINANCE DOMAIN KNOWLEDGE ===\n"
    + _domain_preamble()
    + "\n\n"
    + _questions_section()
    + "\n\n"
    + _gotchas_section()
    + "\n=== END ==="
)


class GeneralAnalyzer(BasePrimitive):
    """Analyse any extracted data to answer a structured-finance question.

    Designed to be gap-aware: it accepts absence_notes from upstream extractors
    and explicitly incorporates data gaps into its reasoning and output.
    """

    name = "analyzer.general"
    version = "0.1.0"
    capability = (
        "Analyse any extracted structured-finance data to answer a question. "
        "Accepts data from any upstream primitive (extractor.general, extractor.table, "
        "extractor.waterfall, connector.loan_tape, etc.) plus optional absence_notes "
        "from steps that certified data as absent. "
        "Returns analysis, key_findings, supporting_evidence with citations, gaps list, "
        "and confidence. Use when domain-specific analyzers don't cover the question."
    )
    inputs = {
        "data": "any: upstream extracted data (dict, list, or any PrimitiveOutput payload).",
        "question": "str: the analytical question to answer.",
        "context": "str, optional: background context about the deal or document.",
        "sources": "dict, optional: {source_label: document_name} for citation context.",
        "absence_notes": "list[str], optional: gap_summary strings from upstream absence-certified steps.",
    }
    outputs = {
        "payload.analysis": "str: full analytical answer to the question.",
        "payload.key_findings": "list[str]: bullet-point findings.",
        "payload.supporting_evidence": "list[{claim, source, page, excerpt}]: cited evidence.",
        "payload.gaps": "list[str]: data that would improve the analysis.",
        "payload.confidence": "float: [0, 1] analytical confidence.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        data: Any = inp.get("data")
        question: str = str(inp.get("question", "") or "").strip()
        context: str = str(inp.get("context", "") or "").strip()
        sources: dict = inp.get("sources", {}) or {}
        absence_notes: list[str] = inp.get("absence_notes", []) or []

        if not question:
            return PrimitiveOutput(
                payload=self._empty(), citations=[], confidence=0.0,
                issues=["question is required."],
            )

        data_text = _serialise_data(data)
        context_section = f"\nBACKGROUND CONTEXT:\n{context}\n" if context else ""
        sources_section = (
            "\nSOURCES:\n" + "\n".join(f"  {k}: {v}" for k, v in sources.items()) + "\n"
            if sources else ""
        )
        gaps_section = ""
        if absence_notes:
            gaps_section = (
                "\nDATA GAPS (these sections could not be extracted from the document):\n"
                + "\n".join(f"  - {note}" for note in absence_notes)
                + "\n"
                "Acknowledge these gaps explicitly in your analysis.\n"
            )

        prompt = (
            f"QUESTION: {question}\n"
            f"{context_section}"
            f"{sources_section}"
            f"{gaps_section}\n"
            "EXTRACTED DATA:\n"
            f"{data_text}\n\n"
            "TASK: Analyse the data above to answer the question. Be specific and quantitative "
            "where the data supports it. Acknowledge any data gaps honestly.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "analysis": str,\n'
            '  "key_findings": list[str],\n'
            '  "supporting_evidence": [\n'
            '    {"claim": str, "source": str, "page": int_or_null, "excerpt": str}\n'
            '  ],\n'
            '  "gaps": list[str],\n'
            '  "confidence": float\n'
            "}\n\n"
            "Fields:\n"
            "  analysis: 2-5 paragraph narrative answer\n"
            "  key_findings: 3-7 bullet-point findings\n"
            "  supporting_evidence: cited facts from the data (not invented)\n"
            "  gaps: data that would allow a more complete answer\n"
            "  confidence: your confidence in the analysis (0-1), lower if gaps exist\n"
        )

        try:
            raw = self._llm(prompt, system=_SYSTEM, max_tokens=2500)
        except Exception as exc:
            return PrimitiveOutput(
                payload=self._empty(), citations=[], confidence=0.0,
                issues=[f"LLM analysis failed: {exc}"],
            )

        if not isinstance(raw, dict):
            return PrimitiveOutput(
                payload=self._empty(), citations=[], confidence=0.0,
                issues=["Analysis returned unexpected format."],
            )

        analysis = str(raw.get("analysis", "")).strip()
        key_findings = [str(f) for f in (raw.get("key_findings", []) or []) if f]
        evidence = [e for e in (raw.get("supporting_evidence", []) or []) if isinstance(e, dict)]
        gaps = [str(g) for g in (raw.get("gaps", []) or []) if g]
        confidence = min(0.95, max(0.0, float(raw.get("confidence", 0.5))))

        # Adjust confidence down for certified gaps
        if absence_notes:
            gap_penalty = min(len(absence_notes) * 0.10, 0.30)
            confidence = max(0.0, confidence - gap_penalty)

        citations: list[Citation] = []
        for ev in evidence:
            source = str(ev.get("source", ""))
            page = ev.get("page")
            excerpt = str(ev.get("excerpt", ""))[:240]
            if source and excerpt:
                loc = f"page={page}" if isinstance(page, int) else "unknown"
                citations.append(Citation(source=source, location=loc, excerpt=excerpt))

        # Extend gaps with absence notes not already reflected
        all_gaps = gaps + [n for n in absence_notes if n not in gaps]

        return PrimitiveOutput(
            payload={
                "analysis": analysis,
                "key_findings": key_findings,
                "supporting_evidence": evidence,
                "gaps": all_gaps,
                "confidence": round(confidence, 4),
            },
            citations=citations,
            confidence=round(confidence, 4),
            issues=[],
            metadata={
                "evidence_items": len(evidence),
                "gap_count": len(all_gaps),
                "absence_notes_provided": len(absence_notes),
            },
        )

    @staticmethod
    def _empty() -> dict:
        return {
            "analysis": "",
            "key_findings": [],
            "supporting_evidence": [],
            "gaps": [],
            "confidence": 0.0,
        }


def _serialise_data(data: Any) -> str:
    """Convert upstream data to a concise text representation for the LLM."""
    if data is None:
        return "(no data provided)"
    if isinstance(data, str):
        return data[:6000]
    try:
        text = json.dumps(data, default=str, indent=2)
        if len(text) > 6000:
            text = text[:5900] + "\n... (truncated)"
        return text
    except Exception:
        return str(data)[:6000]
