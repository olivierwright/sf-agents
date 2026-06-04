"""Shared autonomous extraction loop for LLM-backed extractors.

This module provides the reusable building blocks for the multi-phase
extraction pattern used by WaterfallExtractor, GeneralExtractor, and
TableExtractor:

  1. Try structural strategies (hint-directed, heuristic, density)
  2. Scout the document with the LLM if structural strategies fail
  3. Verify each extraction result (are these real findings?)
  4. Certify absence after exhausting all strategies

Usage:
    from ._autonomous_loop import (
        AutonomousExtractionLoop,
        certify_absence,
        llm_document_scout,
        stratified_sample,
        absence_sample,
    )
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger("sf_agents.extractors.loop")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
HIGH_CONFIDENCE = 0.70          # Accept result immediately above this
PARTIAL_CONFIDENCE_FACTOR = 0.65 # Multiply raw confidence for unverified results
MIN_ABSENCE_CONFIDENCE = 0.75    # Accept absence certification above this

# Maximum candidate pages sent to the LLM per strategy attempt
MAX_CANDIDATE_PAGES = 28
FORWARD_WINDOW = 25
BACKWARD_WINDOW = 3

# Sampling sizes for scout and absence calls
SCOUT_SAMPLE_SIZE = 40
ABSENCE_SAMPLE_SIZE = 45

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
SYSTEM_SCOUT = (
    "You are a structured-finance document analyst. "
    "Your task is to locate a specific section in a prospectus by reading sampled pages. "
    "Be precise about page numbers. Look for section headings, TOC entries, and "
    "structural signals (dense ordinal lists, sub-headings matching the target). "
    "Respond with a single JSON object only."
)

SYSTEM_ABSENCE = (
    "You are a structured-finance document reviewer performing a final audit. "
    "Your task is to determine whether a section is genuinely absent from a document "
    "or whether it was missed due to formatting. Be honest about uncertainty. "
    "Respond with a single JSON object only."
)


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

class AutonomousExtractionLoop:
    """Runs a series of (name, candidate_pages) strategies in priority order.

    The caller supplies:
      - ``strategies``:  iterable of (name, pages) pairs to try
      - ``extractor``:   callable(document, pages, context_hint) → (steps, citations, issues)
      - ``verifier``:    callable(steps, pages) → (ok: bool, note: str)
      - ``make_output``: callable(name, steps, citations, issues) → PrimitiveOutput

    The loop stops at the first strategy that passes verification with
    confidence >= HIGH_CONFIDENCE, or exhausts all strategies.

    After exhaustion, ``best_partial`` holds the attempt with the most steps
    (if any), and ``all_attempts`` holds every (name, steps, citations, issues).
    """

    def __init__(
        self,
        extractor: Callable,
        verifier: Callable,
    ) -> None:
        self._extractor = extractor
        self._verifier = verifier
        self.best_partial: Optional[tuple[str, list, list, list]] = None
        self.all_attempts: list[tuple[str, list, list, list]] = []
        self._tried: set[frozenset[int]] = set()

    def run(
        self,
        document: str,
        strategies: Iterator[tuple[str, list[dict]]],
        all_pages: list[dict],
        context_hint: str,
        make_output: Callable,
    ):
        """Execute strategies, return the first high-confidence PrimitiveOutput or None."""
        for name, candidate_pages in strategies:
            if not candidate_pages:
                continue
            page_key = frozenset(p["page"] for p in candidate_pages)
            if page_key in self._tried:
                continue
            self._tried.add(page_key)

            steps, citations, issues = self._extractor(document, candidate_pages, all_pages, context_hint)

            if steps:
                ok, note = self._verifier(steps, candidate_pages)
                if ok:
                    output = make_output(name, steps, citations, issues, note)
                    if output.confidence >= HIGH_CONFIDENCE:
                        return output
                self.all_attempts.append((name, steps, citations, issues))

        # Update best partial
        if self.all_attempts:
            self.best_partial = max(self.all_attempts, key=lambda x: len(x[1]))

        return None


# ---------------------------------------------------------------------------
# LLM Document Scout
# ---------------------------------------------------------------------------

def llm_document_scout(
    pages: list[dict],
    page_by_num: dict[int, dict],
    document: str,
    target_description: str,
    llm: Callable,
    context_hint: str = "",
) -> list[tuple[str, list[dict]]]:
    """Ask the LLM to locate a target section by scanning sampled pages.

    Returns a list of (strategy_name, candidate_pages) ordered by confidence,
    ready to feed into AutonomousExtractionLoop.
    """
    sample = stratified_sample(pages, SCOUT_SAMPLE_SIZE)
    page_blocks = "\n\n".join(
        f"[PAGE {p['page']}]\n{(p.get('text', '') or '')[:600]}"
        for p in sample
    )
    hint_line = f"\nANALYST HINT: {context_hint}\n" if context_hint else ""

    prompt = (
        f"Document: {document}{hint_line}\n\n"
        f"TARGET: {target_description}\n\n"
        "TASK: Scan the sampled pages below and identify the MOST LIKELY page range "
        "containing the target section. Look for:\n"
        "- Table of Contents entries referencing the target\n"
        "- Section headings matching the target description\n"
        "- Structural content signals (numbered/lettered lists, dense data, tables)\n\n"
        "Return up to 3 candidate locations ordered by confidence (highest first).\n\n"
        "Return JSON:\n"
        "{\n"
        '  "candidates": [\n'
        "    {\n"
        '      "label": str,\n'
        '      "page_start": int,\n'
        '      "page_end": int,\n'
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
        result = llm(prompt, system=SYSTEM_SCOUT, max_tokens=600)
    except Exception as exc:
        logger.debug("Document scout LLM call failed: %s", exc)
        return []

    if not isinstance(result, dict):
        return []

    candidates = result.get("candidates", [])
    if not isinstance(candidates, list):
        return []

    out: list[tuple[str, list[dict]]] = []
    for i, cand in enumerate(candidates[:3]):
        if not isinstance(cand, dict):
            continue
        p_start = cand.get("page_start")
        p_end = cand.get("page_end")
        conf = float(cand.get("confidence", 0))
        if not (isinstance(p_start, int) and isinstance(p_end, int)):
            continue
        if conf < 0.2:
            continue
        lo = max(1, p_start - BACKWARD_WINDOW)
        hi = p_end + 5
        candidate_pages = [
            page_by_num[n] for n in range(lo, hi + 1) if n in page_by_num
        ][:MAX_CANDIDATE_PAGES]
        if candidate_pages:
            label = cand.get("label", f"scout_candidate_{i + 1}")
            out.append((f"scout:{label}", candidate_pages))

    return out


# ---------------------------------------------------------------------------
# Absence certification
# ---------------------------------------------------------------------------

def certify_absence(
    pages: list[dict],
    document: str,
    target_description: str,
    llm: Callable,
) -> dict[str, Any]:
    """Ask the LLM to certify whether the target is genuinely absent.

    Samples the full document and returns a dict with:
      confident_absent: bool
      confidence: float
      explanation: str
      gap_summary: str
      possible_location: str
    """
    sample = absence_sample(pages, ABSENCE_SAMPLE_SIZE)
    page_blocks = "\n\n".join(
        f"[PAGE {p['page']}]\n{(p.get('text', '') or '')[:500]}"
        for p in sample
    )

    prompt = (
        f"Document: {document} (~{len(pages)} pages sampled below)\n\n"
        f"TARGET: {target_description}\n\n"
        "An automated extraction system has exhausted all strategies and found NOTHING. "
        "Perform a final audit. Determine whether:\n"
        "  (a) The target section is GENUINELY ABSENT from this document, OR\n"
        "  (b) The section EXISTS but was MISSED (non-standard heading, embedded content, "
        "different terminology)\n\n"
        "Consider:\n"
        "- TOC entries referencing the target or synonyms\n"
        "- Any page with dense structured data matching the target type\n"
        "- Whether this document type typically always contains this section\n\n"
        "Return JSON:\n"
        "{\n"
        '  "confident_absent": bool,\n'
        '  "confidence": float,\n'
        '  "explanation": str,\n'
        '  "gap_summary": str,\n'
        '  "possible_location": str\n'
        "}\n\n"
        "Fields:\n"
        "  confident_absent: true only if you believe the target is truly not in the doc\n"
        "  confidence: your certainty (0-1)\n"
        "  explanation: technical reason for absence or what looks different\n"
        "  gap_summary: 2-3 sentences for the end-user: what's missing and its analytical impact\n"
        "  possible_location: if not absent, where to look (page/section); else empty string\n\n"
        f"SAMPLED PAGES:\n{page_blocks}"
    )

    try:
        result = llm(prompt, system=SYSTEM_ABSENCE, max_tokens=500)
        if isinstance(result, dict):
            return result
    except Exception as exc:
        logger.debug("Absence certification LLM call failed: %s", exc)

    return {
        "confident_absent": False,
        "confidence": 0.0,
        "explanation": "Absence check failed.",
        "gap_summary": "",
        "possible_location": "",
    }


# ---------------------------------------------------------------------------
# Page hint parsing (shared utility)
# ---------------------------------------------------------------------------

def pages_from_hint(
    pages: list[dict],
    hint: str,
    page_by_num: dict[int, dict],
) -> list[dict]:
    """Parse a page range or section reference from a context hint string."""
    hint_lower = hint.lower()

    for pattern in (
        r"page[s]?\s+(\d+)\s*[-–to]+\s*(\d+)",
        r"\b(\d+)\s*[-–]\s*(\d+)\b",
        r"\b(\d+)\s+to\s+(\d+)\b",
    ):
        m = re.search(pattern, hint_lower)
        if m:
            lo = max(1, int(m.group(1)) - BACKWARD_WINDOW)
            hi = int(m.group(2)) + 5
            result = [page_by_num[n] for n in range(lo, hi + 1) if n in page_by_num]
            if result:
                return result[:MAX_CANDIDATE_PAGES]

    m = re.search(r"\bpage\s+(\d+)\b", hint_lower)
    if m:
        pn = int(m.group(1))
        return [
            page_by_num[n]
            for n in range(max(1, pn - BACKWARD_WINDOW), pn + FORWARD_WINDOW + 1)
            if n in page_by_num
        ][:MAX_CANDIDATE_PAGES]

    m = re.search(r"section\s+([\d.]+)", hint_lower) or re.search(r"\b([\d]+\.\d+)\b", hint_lower)
    if m:
        sec = m.group(1)
        tagged = [p for p in pages if sec in (p.get("text", "") or "")]
        if tagged:
            start = max(1, min(p["page"] for p in tagged) - BACKWARD_WINDOW)
            return [
                page_by_num[n]
                for n in range(start, start + MAX_CANDIDATE_PAGES)
                if n in page_by_num
            ]

    return []


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------

def stratified_sample(pages: list[dict], n: int) -> list[dict]:
    """Sample pages spread across the document, weighting the middle section."""
    if len(pages) <= n:
        return pages
    total = len(pages)
    lo_idx = total * 15 // 100
    hi_idx = total * 85 // 100
    middle = pages[lo_idx:hi_idx]
    step = max(1, len(middle) // (n * 3 // 4))
    sampled = middle[::step][:n * 3 // 4]
    front = pages[:lo_idx:max(1, lo_idx // 8)][:n // 8]
    back = pages[hi_idx::max(1, (total - hi_idx) // 8)][:n // 8]
    combined = sorted(
        {p["page"]: p for p in front + sampled + back}.values(),
        key=lambda p: p["page"],
    )
    return combined[:n]


def absence_sample(pages: list[dict], n: int) -> list[dict]:
    """Sample for absence certification: TOC pages + even stride through the body."""
    if len(pages) <= n:
        return pages
    front = pages[:20]
    stride = max(1, len(pages) // (n - min(20, len(pages))))
    body = pages[20::stride]
    combined = sorted(
        {p["page"]: p for p in front + body}.values(),
        key=lambda p: p["page"],
    )
    return combined[:n]
