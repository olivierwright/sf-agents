"""Locate a named section in a prospectus or PDF document.

Standalone document-scout primitive. Any extractor that needs to narrow its
search before running its main extraction can call this primitive first in
the plan, then pass its ``page_start``/``page_end`` output as a hint.

The locator samples pages from across the document and asks the LLM to
identify the most likely page range for the target section, looking at:
  - Table of contents entries
  - Section headings matching the target description
  - Structural content signals (numbered lists, tables, dense data)

It returns up to three ranked candidate locations so downstream steps can
fall back to alternatives if the top candidate yields no results.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ._autonomous_loop import (
    SCOUT_SAMPLE_SIZE,
    SYSTEM_SCOUT,
    stratified_sample,
)

JsonLLM = Callable[..., Any]


class LocatorExtractor(BasePrimitive):
    """Locate any named section in a PDF document using LLM document scouting.

    Returns page-range candidates so downstream extractors can jump straight
    to the right pages rather than scanning the whole document.
    """

    name = "extractor.locator"
    version = "0.1.0"
    capability = (
        "Locate a named section, table, or data type within a prospectus or PDF "
        "by scanning sampled pages with an LLM. Returns page_start, page_end, "
        "section_name, confidence, and up to 3 ranked candidate locations. "
        "Use before other extractors when the target section's page range is unknown. "
        "Input pages from connector.prospectus or connector.pdf_document."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: pages from a connector.",
        "document": "str: source document name.",
        "target_description": "str: what to locate (e.g. 'Priority of Payments waterfall', 'capital structure table', 'reserve fund definition').",
        "context_hint": "str, optional: additional context or analyst hint.",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.page_start": "int: best-estimate start page of the target section.",
        "payload.page_end": "int: best-estimate end page of the target section.",
        "payload.section_name": "str: detected section name/heading.",
        "payload.candidates": "list[{label, page_start, page_end, confidence, reasoning}]: all candidate locations.",
        "payload.toc_reference_found": "bool: whether a TOC entry was found.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages: list[dict[str, Any]] = inp.get("pages", []) or []
        document: str = inp.get("document", "document")
        target: str = str(inp.get("target_description", "") or "").strip()
        context_hint: str = str(inp.get("context_hint", "") or "").strip()

        if not target:
            return PrimitiveOutput(
                payload={"document": document, "page_start": None, "page_end": None,
                         "section_name": "", "candidates": [], "toc_reference_found": False},
                citations=[],
                confidence=0.0,
                issues=["target_description is required."],
            )

        sample = stratified_sample(pages, SCOUT_SAMPLE_SIZE)
        page_blocks = "\n\n".join(
            f"[PAGE {p['page']}]\n{(p.get('text', '') or '')[:600]}"
            for p in sample
        )
        hint_line = f"\nANALYST HINT: {context_hint}\n" if context_hint else ""

        prompt = (
            f"Document: {document}{hint_line}\n\n"
            f"TARGET: {target}\n\n"
            "TASK: Scan the sampled pages below and identify the MOST LIKELY page range "
            "containing the target. Look for:\n"
            "- TOC entries that reference the target or close synonyms\n"
            "- Section headings matching the target description\n"
            "- Structural signals (numbered/lettered lists, tables, dense data columns)\n\n"
            "Return up to 3 candidate locations ordered by confidence (highest first).\n\n"
            "Return JSON:\n"
            "{\n"
            '  "candidates": [\n'
            "    {\n"
            '      "label": str,\n'
            '      "page_start": int,\n'
            '      "page_end": int,\n'
            '      "section_name": str,\n'
            '      "confidence": float,\n'
            '      "reasoning": str\n'
            "    }\n"
            "  ],\n"
            '  "toc_reference_found": bool,\n'
            '  "overall_confidence": float\n'
            "}\n\n"
            f"SAMPLED PAGES:\n{page_blocks}"
        )

        try:
            raw = self._llm(prompt, system=SYSTEM_SCOUT, max_tokens=600)
        except Exception as exc:
            return PrimitiveOutput(
                payload={"document": document, "page_start": None, "page_end": None,
                         "section_name": "", "candidates": [], "toc_reference_found": False},
                citations=[],
                confidence=0.0,
                issues=[f"LLM scout failed: {exc}"],
            )

        if not isinstance(raw, dict):
            return PrimitiveOutput(
                payload={"document": document, "page_start": None, "page_end": None,
                         "section_name": "", "candidates": [], "toc_reference_found": False},
                citations=[],
                confidence=0.0,
                issues=["Scout returned unexpected format."],
            )

        candidates = raw.get("candidates", [])
        toc_found = bool(raw.get("toc_reference_found", False))
        overall_conf = float(raw.get("overall_confidence", 0))

        # Validate and clean candidates
        clean_candidates = []
        citations: list[Citation] = []
        for cand in (candidates or [])[:3]:
            if not isinstance(cand, dict):
                continue
            p_start = cand.get("page_start")
            p_end = cand.get("page_end")
            if not (isinstance(p_start, int) and isinstance(p_end, int)):
                continue
            clean = {
                "label": str(cand.get("label", "")),
                "page_start": p_start,
                "page_end": p_end,
                "section_name": str(cand.get("section_name", "")),
                "confidence": float(cand.get("confidence", 0)),
                "reasoning": str(cand.get("reasoning", "")),
            }
            clean_candidates.append(clean)
            citations.append(Citation(
                source=document,
                location=f"pages={p_start}-{p_end}",
                excerpt=str(cand.get("reasoning", ""))[:200],
            ))

        best = clean_candidates[0] if clean_candidates else {}
        confidence = min(0.95, overall_conf * (1.1 if toc_found else 1.0))

        return PrimitiveOutput(
            payload={
                "document": document,
                "page_start": best.get("page_start"),
                "page_end": best.get("page_end"),
                "section_name": best.get("section_name", ""),
                "candidates": clean_candidates,
                "toc_reference_found": toc_found,
            },
            citations=citations,
            confidence=round(confidence, 4),
            issues=[] if clean_candidates else ["No candidate locations found."],
            metadata={
                "sample_pages": len(sample),
                "total_pages": len(pages),
                "candidates_found": len(clean_candidates),
            },
        )
