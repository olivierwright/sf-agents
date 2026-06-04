"""Extract the priority-of-payments waterfall from prospectus pages.

Autonomous reasoning loop — keeps trying until one of two terminal conditions:

  FOUND:  extraction passes verification with confidence >= HIGH_CONFIDENCE
  ABSENT: LLM certifies, after exhausting all strategies, that the waterfall
          genuinely does not appear in the document

Internal loop phases:

  Phase 1 — Structural strategies (fast, no extra LLM calls):
    1a. Hint-directed page range (analyst or prior-run context hint)
    1b. Strict section anchor  (section heading + real ordinal steps)
    1c. Cascade-header search  (subsection headings alone)
    1d. Expanded density scoring

  Phase 2 — LLM Document Scout:
    Samples pages from across the document and asks the LLM to locate the
    waterfall section — just as a human analyst would leaf through the document.

  Phase 3 — Best partial result:
    If any attempt found steps that did not pass verification, the best one
    is returned with a reduced confidence and a verification warning.

  Phase 4 — Absence certification:
    Asks the LLM to certify whether the waterfall is genuinely absent.
    Sets absence_certified=True / absence_explanation so the executor skips
    HITL and the synthesizer explains the gap.

Shared loop machinery (AutonomousExtractionLoop, certify_absence,
llm_document_scout, stratified_sample, absence_sample) is in
_autonomous_loop.py — imported here rather than duplicated.

Domain knowledge (Dutch RMBS / EU STS):
  - Section "5.2 Priorities of Payments" is where the waterfall lives.
  - Three cascades: Revenue/Interest, Principal/Redemption, Post-Enforcement.
  - Actual steps use ordinal language: "first,", "second,", …
  - Risk-factor and summary pages cross-reference the section but list no steps.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ._autonomous_loop import (
    HIGH_CONFIDENCE,
    MAX_CANDIDATE_PAGES,
    MIN_ABSENCE_CONFIDENCE,
    PARTIAL_CONFIDENCE_FACTOR,
    certify_absence,
    llm_document_scout,
    pages_from_hint,
    stratified_sample,
)

JsonLLM = Callable[..., Any]

# ---------------------------------------------------------------------------
# Thresholds / sizes
# ---------------------------------------------------------------------------
_MIN_STEPS_PER_CASCADE = 5
_MIN_CASCADES_EXPECTED = 2
_MIN_ORDINALS_FOR_REAL_PAGE = 3
_FORWARD_WINDOW = 28
_BACKWARD_WINDOW = 3

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
_SYSTEM_EXTRACT = (
    "You are a structured-finance analyst specialising in RMBS waterfall mechanics. "
    "You have deep knowledge of EU/Dutch RMBS prospectus structure. "
    "The Priority of Payments section always contains three distinct cascades: "
    "(1) Revenue/Interest, (2) Principal/Redemption, (3) Post-Enforcement. "
    "Each cascade step uses ordinal language: 'first, to pay...', 'second, to pay...'. "
    "Extract ONLY actual waterfall steps — not summaries, risk-factor mentions, or "
    "conditions-language that cross-references the waterfall without listing its steps. "
    "Every excerpt must be copied verbatim from the cited page."
)

_SYSTEM_VERIFY = (
    "You are a structured-finance compliance reviewer. "
    "Your task is to verify whether extracted data is genuine or a false positive. "
    "Be critical. Respond with a single JSON object only."
)

# ---------------------------------------------------------------------------
# Domain keyword constants
# ---------------------------------------------------------------------------
_SECTION_HEADERS = (
    "priorities of payments",
    "priority of payments",
    "application of funds",
)

_CONTENT_SIGNALS = (
    "following order of priority",
    "following amounts in the following",
    "in the following order of priority",
    "the following priority",
    "following priority of payments",
    "in the order of priority",
    "in the following priority",
    "in the following order",
)

_CASCADE_HEADERS: dict[str, tuple[str, ...]] = {
    "revenue_interest": (
        "revenue priority",
        "interest priority of payments",
        "available interest funds",
        "interest available funds",
        "revenue available funds",
        "revenue priority of payments",
        "available revenue funds",
    ),
    "principal_redemption": (
        "redemption priority",
        "principal priority of payments",
        "available principal funds",
        "principal available funds",
        "redemption available funds",
        "redemption priority of payments",
    ),
    "post_enforcement": (
        "post-enforcement priority",
        "enforcement priority of payments",
        "following an enforcement notice",
        "after delivery of an enforcement notice",
        "following service of an enforcement notice",
        "post enforcement priority",
        "post-enforcement priority of payments",
    ),
}

_ORDINALS = (
    "first,", "second,", "third,", "fourth,", "fifth,",
    "sixth,", "seventh,", "eighth,", "ninth,", "tenth,",
    "eleventh,", "twelfth,", "thirteenth,", "fourteenth,",
    "fifteenth,", "sixteenth,",
)
_PAYMENT_WORDS = (
    "payable", "due and payable", "fees", "expenses",
    "interest", "principal", "trustee", "servicer",
    "swap", "hedging", "issuer", "noteholders", "administrator",
)


class WaterfallExtractor(BasePrimitive):
    """Autonomous waterfall extraction with multi-phase retry and absence certification."""

    name = "extractor.waterfall"
    version = "0.5.0"
    capability = (
        "Extract the complete priority-of-payments waterfall from a prospectus. "
        "Uses an autonomous reasoning loop: hint-directed, strict section anchor, "
        "cascade-header search, density scoring, LLM document scouting. "
        "Verifies each extraction. Returns absence_certified=True with gap_summary "
        "when data is genuinely absent after exhaustive search. "
        "Use connector.prospectus to obtain the pages input."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: reference connector.prospectus payload.pages.",
        "document": "str: source document name.",
        "context_hint": "str, optional: analyst hint (page range, section name) for retry.",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.waterfall_steps": "list[{rank, waterfall_type, beneficiary, amount_basis, conditions, page, excerpt}].",
        "payload.cascades_found": "list[str]: which cascades were found.",
        "payload.discovery_method": "str: which strategy succeeded.",
        "payload.absence_certified": "bool: True when exhaustive search confirmed absence.",
        "payload.absence_explanation": "str: why the waterfall is absent or could not be found.",
        "payload.strategies_tried": "list[str]: all strategies that were attempted.",
        "payload.gap_summary": "str: synthesizer-ready explanation of what is missing and why.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as _llm
            llm = _llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages: list[dict[str, Any]] = inp.get("pages", []) or []
        document: str = inp.get("document", "document")
        context_hint: str = str(inp.get("context_hint", "") or "").strip()

        page_by_num = {p["page"]: p for p in pages}
        tried_page_sets: set[frozenset[int]] = set()
        strategies_tried: list[str] = []
        all_attempts: list[tuple[str, list, list, list]] = []

        # ------------------------------------------------------------------
        # Phase 1: Structural strategies
        # ------------------------------------------------------------------
        for strategy_name, candidate_pages in _build_structural_strategies(pages, context_hint, page_by_num):
            if not candidate_pages:
                continue
            page_key = frozenset(p["page"] for p in candidate_pages)
            if page_key in tried_page_sets:
                continue
            tried_page_sets.add(page_key)
            strategies_tried.append(strategy_name)

            steps, citations, issues = self._extract(document, candidate_pages, pages, context_hint)

            if steps:
                ok, note = self._verify(steps, candidate_pages)
                if ok:
                    result = self._make_success(document, steps, citations, issues, strategy_name, strategies_tried, note)
                    if result.confidence >= HIGH_CONFIDENCE:
                        return result
                all_attempts.append((strategy_name, steps, citations, issues))

        # ------------------------------------------------------------------
        # Phase 2: LLM Document Scout
        # ------------------------------------------------------------------
        strategies_tried.append("llm_document_scout")
        scout_candidates = llm_document_scout(
            pages, page_by_num, document,
            "Priority of Payments waterfall section with Revenue/Interest, "
            "Principal/Redemption, and Post-Enforcement cascades",
            self._llm, context_hint,
        )

        for scout_name, scout_pages in scout_candidates:
            if not scout_pages:
                continue
            page_key = frozenset(p["page"] for p in scout_pages)
            if page_key in tried_page_sets:
                continue
            tried_page_sets.add(page_key)
            strategies_tried.append(scout_name)

            steps, citations, issues = self._extract(document, scout_pages, pages, context_hint)

            if steps:
                ok, note = self._verify(steps, scout_pages)
                if ok:
                    result = self._make_success(document, steps, citations, issues, scout_name, strategies_tried, note)
                    if result.confidence >= HIGH_CONFIDENCE:
                        return result
                all_attempts.append((scout_name, steps, citations, issues))

        # ------------------------------------------------------------------
        # Phase 3: Best partial result
        # ------------------------------------------------------------------
        if all_attempts:
            best_name, best_steps, best_cit, best_issues = max(all_attempts, key=lambda x: len(x[1]))
            cascades = sorted({s["waterfall_type"] for s in best_steps})
            raw_conf = _compute_confidence(best_steps, best_cit, best_issues, cascades)
            partial_conf = round(raw_conf * PARTIAL_CONFIDENCE_FACTOR, 4)
            return PrimitiveOutput(
                payload={
                    "document": document,
                    "waterfall_steps": best_steps,
                    "cascades_found": cascades,
                    "discovery_method": best_name,
                    "partial": True,
                    "absence_certified": False,
                    "absence_explanation": "",
                    "gap_summary": (
                        f"Waterfall steps were found via '{best_name}' but could not be "
                        "fully verified as genuine cascade steps. "
                        f"Cascades found: {cascades or 'none'}."
                    ),
                    "strategies_tried": strategies_tried,
                },
                citations=best_cit,
                confidence=partial_conf,
                issues=best_issues + ["Partial result — verification not passed."],
                metadata={"steps_found": len(best_steps), "strategies_tried": strategies_tried},
            )

        # ------------------------------------------------------------------
        # Phase 4: Absence certification
        # ------------------------------------------------------------------
        strategies_tried.append("absence_certification")
        absence = certify_absence(
            pages, document,
            "Priority of Payments waterfall (Revenue/Interest, Principal/Redemption, Post-Enforcement cascades)",
            self._llm,
        )

        if absence.get("confident_absent") and absence.get("confidence", 0) >= MIN_ABSENCE_CONFIDENCE:
            explanation = absence.get("explanation", "Waterfall section not found.")
            gap = absence.get("gap_summary", explanation)
            if absence.get("possible_location"):
                gap += f" Possible location: {absence['possible_location']}"
            return PrimitiveOutput(
                payload={
                    "document": document,
                    "waterfall_steps": [],
                    "cascades_found": [],
                    "discovery_method": "absence_certified",
                    "absence_certified": True,
                    "absence_explanation": explanation,
                    "gap_summary": gap,
                    "strategies_tried": strategies_tried,
                },
                citations=[],
                confidence=round(absence["confidence"], 4),
                issues=[explanation],
                metadata={"steps_found": 0, "strategies_tried": strategies_tried},
            )

        return PrimitiveOutput(
            payload={
                "document": document,
                "waterfall_steps": [],
                "cascades_found": [],
                "discovery_method": "none",
                "absence_certified": False,
                "absence_explanation": (
                    "Exhausted all strategies and could not certify absence. "
                    "The document may use non-standard formatting."
                ),
                "gap_summary": (
                    "The Priority of Payments waterfall could not be extracted. "
                    f"Strategies tried: {', '.join(strategies_tried)}."
                ),
                "strategies_tried": strategies_tried,
            },
            citations=[],
            confidence=0.0,
            issues=["No waterfall data found after exhausting all strategies."],
            metadata={"steps_found": 0, "strategies_tried": strategies_tried},
        )

    # -----------------------------------------------------------------------
    # Core LLM calls
    # -----------------------------------------------------------------------

    def _extract(
        self,
        document: str,
        candidate_pages: list[dict],
        all_pages: list[dict],
        context_hint: str,
    ) -> tuple[list[dict], list[Citation], list[str]]:
        prompt = _build_extraction_prompt(document, candidate_pages, context_hint)
        try:
            raw = self._llm(prompt, system=_SYSTEM_EXTRACT, max_tokens=6000)
        except Exception as exc:
            return [], [], [f"LLM extraction failed: {exc}"]

        records = _coerce_records(raw)
        valid_pages = {p["page"] for p in all_pages}
        steps: list[dict] = []
        citations: list[Citation] = []
        issues: list[str] = []

        for i, rec in enumerate(records):
            beneficiary = str(rec.get("beneficiary", "")).strip()
            if not beneficiary:
                continue
            rank = rec.get("rank", i + 1)
            excerpt = str(rec.get("excerpt", "")).strip()
            page = rec.get("page")
            steps.append({
                "rank": rank,
                "waterfall_type": str(rec.get("waterfall_type", "revenue_interest")).strip(),
                "beneficiary": beneficiary,
                "amount_basis": str(rec.get("amount_basis", "")).strip(),
                "conditions": str(rec.get("conditions", "")).strip(),
                "page": page,
                "excerpt": excerpt,
            })
            if isinstance(page, int) and page in valid_pages:
                citations.append(Citation(source=document, location=f"page={page}", excerpt=excerpt[:240]))
            else:
                issues.append(f"Step rank {rank} ({beneficiary!r}): no resolvable page.")

        return steps, citations, issues

    def _verify(
        self,
        steps: list[dict],
        candidate_pages: list[dict],
    ) -> tuple[bool, str]:
        # Fast path: clearly real if enough steps across enough cascades
        cascades = {s["waterfall_type"] for s in steps}
        if len(steps) >= 8 and len(cascades) >= 2:
            return True, "fast-path: sufficient steps and cascades"

        step_sample = "\n".join(
            f"  [{s['waterfall_type']}] rank={s['rank']} | "
            f"beneficiary={s['beneficiary']!r} | excerpt={s['excerpt'][:80]!r}"
            for s in steps[:20]
        )
        page_sample = "\n\n".join(
            f"[PAGE {p['page']}]\n{(p.get('text', '') or '')[:800]}"
            for p in sorted(candidate_pages, key=lambda x: x.get("page", 0))[:6]
        )
        prompt = (
            f"EXTRACTED STEPS ({len(steps)}):\n{step_sample}\n\n"
            f"SAMPLE SOURCE PAGES:\n{page_sample}\n\n"
            "Are these ACTUAL Priority of Payments cascade steps (ranked ordinal steps, "
            "named beneficiaries, payment types) or are they false positives "
            "(cross-references, risk-factor text, summaries)?\n"
            'Return JSON: {"valid": bool, "confidence": float, "note": str}'
        )
        try:
            result = self._llm(prompt, system=_SYSTEM_VERIFY, max_tokens=300)
            if isinstance(result, dict):
                return bool(result.get("valid", False)), str(result.get("note", ""))
        except Exception:
            pass
        # Heuristic fallback
        has_ordinals = any(
            any(o.rstrip(",") in s["excerpt"].lower() for o in _ORDINALS[:6])
            for s in steps
        )
        return has_ordinals, "heuristic fallback"

    def _make_success(
        self,
        document: str,
        steps: list[dict],
        citations: list[Citation],
        issues: list[str],
        strategy_name: str,
        strategies_tried: list[str],
        verify_note: str,
    ) -> PrimitiveOutput:
        cascades = sorted({s["waterfall_type"] for s in steps})
        confidence = _compute_confidence(steps, citations, issues, cascades)
        return PrimitiveOutput(
            payload={
                "document": document,
                "waterfall_steps": steps,
                "cascades_found": cascades,
                "discovery_method": strategy_name,
                "absence_certified": False,
                "absence_explanation": "",
                "gap_summary": "",
                "strategies_tried": strategies_tried,
                "verification_note": verify_note,
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={
                "steps_found": len(steps),
                "cascades_found": cascades,
                "strategies_tried": strategies_tried,
            },
        )


# ---------------------------------------------------------------------------
# Structural strategy builders
# ---------------------------------------------------------------------------

def _build_structural_strategies(
    pages: list[dict],
    context_hint: str,
    page_by_num: dict[int, dict],
):
    if context_hint:
        hint_pages = pages_from_hint(pages, context_hint, page_by_num)
        if hint_pages:
            yield ("hint_directed", hint_pages)

    anchor_pages = _strict_anchor_strategy(pages, page_by_num)
    if anchor_pages:
        yield ("section_anchor_strict", anchor_pages)

    cascade_pages = _cascade_header_strategy(pages, page_by_num)
    if cascade_pages:
        yield ("cascade_header", cascade_pages)

    density_pages = _density_strategy(pages, threshold=3)
    if density_pages:
        yield ("density_scoring", density_pages)


def _is_real_waterfall_page(page: dict) -> bool:
    text = (page.get("text", "") or "").lower()
    has_header = any(h in text for h in _SECTION_HEADERS)
    has_cascade = any(h in text for hs in _CASCADE_HEADERS.values() for h in hs)
    ordinal_count = sum(1 for o in _ORDINALS if o in text)
    has_content = any(p in text for p in _CONTENT_SIGNALS)
    return (
        ((has_header or has_cascade) and ordinal_count >= _MIN_ORDINALS_FOR_REAL_PAGE)
        or (has_content and ordinal_count >= 2)
    )


def _strict_anchor_strategy(pages: list[dict], page_by_num: dict[int, dict]) -> list[dict]:
    anchors = [p for p in pages if _is_real_waterfall_page(p)]
    if not anchors:
        return []
    first = min(p["page"] for p in anchors)
    start = max(1, first - _BACKWARD_WINDOW)
    return [
        page_by_num[n] for n in range(start, first + _FORWARD_WINDOW + 1)
        if n in page_by_num
    ][:MAX_CANDIDATE_PAGES]


def _cascade_header_strategy(pages: list[dict], page_by_num: dict[int, dict]) -> list[dict]:
    tagged = [
        p for p in pages
        if any(h in (p.get("text", "") or "").lower() for hs in _CASCADE_HEADERS.values() for h in hs)
    ]
    if not tagged:
        return []
    nums = sorted(p["page"] for p in tagged)
    start = max(1, nums[0] - _BACKWARD_WINDOW)
    end = max(nums) + _FORWARD_WINDOW
    return [page_by_num[n] for n in range(start, end + 1) if n in page_by_num][:MAX_CANDIDATE_PAGES]


def _density_strategy(pages: list[dict], threshold: int = 3) -> list[dict]:
    scored = sorted(
        ((p, _score_page(p)) for p in pages),
        key=lambda x: (-x[1], x[0].get("page", 0)),
    )
    return [p for p, score in scored if score >= threshold][:MAX_CANDIDATE_PAGES]


def _score_page(page: dict) -> int:
    text = (page.get("text", "") or "").lower()
    return (
        sum(1 for kw in _SECTION_HEADERS if kw in text) * 2
        + min(sum(1 for o in _ORDINALS if o in text), 8) * 4
        + min(sum(1 for pw in _PAYMENT_WORDS if pw in text), 6)
        + sum(1 for hs in _CASCADE_HEADERS.values() for h in hs if h in text) * 3
        + sum(1 for p in _CONTENT_SIGNALS if p in text) * 5
    )


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _compute_confidence(
    steps: list[dict],
    citations: list[Citation],
    issues: list[str],
    cascades_found: list[str],
) -> float:
    n = len(steps)
    if n == 0:
        return 0.0
    citation_cov = len(citations) / n
    cascade_cov = min(len(cascades_found) / _MIN_CASCADES_EXPECTED, 1.0)
    steps_per_cascade = n / max(len(cascades_found), 1)
    step_density = min(steps_per_cascade / _MIN_STEPS_PER_CASCADE, 1.0)
    issue_penalty = min(len(issues) * 0.04, 0.25)
    raw = 0.40 * citation_cov + 0.30 * cascade_cov + 0.20 * step_density - issue_penalty
    return round(max(0.0, min(0.95, raw)), 4)


# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

def _build_extraction_prompt(document: str, pages: list[dict], context_hint: str = "") -> str:
    sorted_pages = sorted(pages, key=lambda p: p.get("page", 0))
    page_range = (
        f"{sorted_pages[0]['page']}–{sorted_pages[-1]['page']}" if sorted_pages else "unknown"
    )
    blocks = [
        f"[PAGE {p['page']}]\n{(p.get('text', '') or '').strip()[:3500]}"
        for p in sorted_pages if (p.get("text", "") or "").strip()
    ]
    corpus = "\n\n".join(blocks) or "(no text available)"

    hint_section = (
        f"\nANALYST HINT: {context_hint}\n"
        "Focus on the page range or section specified. Extract ordinal steps even if "
        "the heading is non-standard.\n"
    ) if context_hint else ""

    return (
        f"Document: {document} — pages {page_range}\n"
        f"{hint_section}\n"
        "CASCADES:\n"
        "• Revenue/Interest: 'Revenue Priority of Payments' or 'Available Interest Funds'\n"
        "• Principal/Redemption: 'Redemption Priority of Payments' or 'Available Principal Funds'\n"
        "• Post-Enforcement: references 'Enforcement Notice'\n\n"
        "Actual steps use ordinal language: 'first,', 'second,', …\n"
        "IGNORE risk-factor and summary pages that mention the waterfall without listing steps.\n\n"
        "TASK: Extract ALL waterfall steps. For each:\n"
        "  rank (int), waterfall_type (revenue_interest|principal_redemption|post_enforcement),\n"
        "  beneficiary (str), amount_basis (str), conditions (str), page (int), excerpt (str ≤150 chars verbatim)\n\n"
        "Return ONLY a JSON array. [] if no real steps found.\n\n"
        f"PAGES:\n{corpus}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        for key in ("steps", "waterfall", "waterfall_steps", "items", "results"):
            if isinstance(raw.get(key), list):
                return [r for r in raw[key] if isinstance(r, dict)]
        return [raw]
    return []
