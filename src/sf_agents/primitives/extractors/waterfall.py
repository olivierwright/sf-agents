"""Extract the priority-of-payments waterfall from prospectus pages.

LLM-backed. Pre-filters pages that mention waterfall keywords before asking
the model for the ordered steps. Every step gets a verbatim excerpt citation.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a structured-finance analyst specialising in waterfall mechanics. "
    "Extract the complete priority-of-payments waterfall from the prospectus pages. "
    "Never invent text: each step's excerpt must be copied verbatim from the page you cite."
)

_KEYWORDS = {"priority of payments", "waterfall", "available funds", "interest proceeds", "principal proceeds"}

# Ordinal markers that appear in actual waterfall text ("first, any fees…")
_ORDINALS = ("first,", "second,", "third,", "fourth,", "fifth,",
             "sixth,", "seventh,", "eighth,", "ninth,", "tenth,")
_PAYMENT_WORDS = ("payable", "due and payable", "fees", "expenses", "interest", "principal")

# Maximum candidate pages sent to the LLM — keeps prompts focused and fast
_MAX_CANDIDATE_PAGES = 15
# Minimum steps expected in a real RMBS waterfall (used in completeness scoring)
_MIN_EXPECTED_STEPS = 8


class WaterfallExtractor(BasePrimitive):
    """Extract the priority-of-payments waterfall from prospectus pages.

    Input args:
        pages (list[dict]): ``[{"page": int, "text": str}, ...]`` from a connector.
        document (str): Source document name (for citations).

    Payload:
        ``{"document": str, "waterfall_steps": [{rank, beneficiary, amount_basis,
           conditions, page, excerpt}, ...]}``
    """

    name = "extractor.waterfall"
    version = "0.1.0"
    capability = (
        "Extract the priority-of-payments (waterfall) from prospectus pages. "
        "Returns each waterfall step with its priority rank, beneficiary, amount "
        "basis, conditions, source page number, and a verbatim excerpt. "
        "Use connector.prospectus to obtain the pages input."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: reference connector.prospectus payload.pages.",
        "document": "str: source document name; reference connector.prospectus payload.document.",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.waterfall_steps": (
            "list[{rank:int, beneficiary:str, amount_basis:str, conditions:str, "
            "page:int, excerpt:str}]: ordered waterfall steps."
        ),
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages: list[dict[str, Any]] = inp.get("pages", []) or []
        document: str = inp.get("document", "document")
        context_hint: str = str(inp.get("context_hint", "") or "").strip()

        candidate_pages = _candidate_pages(pages, _KEYWORDS)
        if not candidate_pages:
            return PrimitiveOutput(
                payload={"document": document, "waterfall_steps": []},
                citations=[],
                confidence=0.0,
                issues=["No waterfall-related pages found in document."],
                metadata={"candidate_pages": []},
            )

        prompt = _build_prompt(document, candidate_pages, context_hint=context_hint)
        try:
            raw = self._llm(prompt, system=_SYSTEM, max_tokens=4096)
        except Exception as exc:
            return PrimitiveOutput(
                payload={"document": document, "waterfall_steps": []},
                citations=[],
                confidence=0.0,
                issues=[f"LLM extraction failed: {exc}"],
                metadata={"candidate_pages": [p["page"] for p in candidate_pages]},
            )
        records = _coerce_records(raw)

        valid_pages = {p["page"]: p["text"] for p in pages}
        steps: list[dict[str, Any]] = []
        citations: list[Citation] = []
        issues: list[str] = []

        for i, rec in enumerate(records):
            rank = rec.get("rank", i + 1)
            beneficiary = str(rec.get("beneficiary", "")).strip()
            amount_basis = str(rec.get("amount_basis", "")).strip()
            conditions = str(rec.get("conditions", "")).strip()
            excerpt = str(rec.get("excerpt", "")).strip()
            page = rec.get("page")
            waterfall_type = str(rec.get("waterfall_type", "revenue_interest")).strip()

            if not beneficiary:
                continue

            step = {
                "rank": rank,
                "waterfall_type": waterfall_type,
                "beneficiary": beneficiary,
                "amount_basis": amount_basis,
                "conditions": conditions,
                "page": page,
                "excerpt": excerpt,
            }
            steps.append(step)

            if isinstance(page, int) and page in valid_pages:
                citations.append(
                    Citation(source=document, location=f"page={page}", excerpt=excerpt[:240])
                )
            else:
                issues.append(f"Step rank {rank} ({beneficiary!r}): no resolvable page cited.")

        confidence = _compute_confidence(steps, citations, issues)

        return PrimitiveOutput(
            payload={"document": document, "waterfall_steps": steps},
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={"candidate_pages": [p["page"] for p in candidate_pages], "steps_found": len(steps)},
        )


def _score_page(page: dict) -> int:
    """Score a page by waterfall relevance.

    Highly relevant pages (actual waterfall sections) have BOTH ordinal markers
    ('first,', 'second,', …) and payment keywords. Keyword-only pages (risk
    factors, summaries) score lower and are deprioritised.
    """
    text = (page.get("text", "") or "").lower()
    keyword_score = sum(1 for kw in _KEYWORDS if kw in text)
    ordinal_score = sum(1 for o in _ORDINALS if o in text)
    payment_score = sum(1 for pw in _PAYMENT_WORDS if pw in text)
    # Ordinal + payment overlap is the strongest signal for an actual waterfall page
    return keyword_score * 2 + min(ordinal_score, 5) * 3 + min(payment_score, 6) * 1


def _candidate_pages(pages: list[dict], keywords: set[str]) -> list[dict]:
    """Return the top waterfall-relevant pages (capped at _MAX_CANDIDATE_PAGES).

    Pages are scored by waterfall-language density. Only pages with a positive
    score are included; if none score positively, we fall back to the first 3
    pages so the LLM always has something to work with.
    """
    scored = sorted(
        ((p, _score_page(p)) for p in pages),
        key=lambda x: (-x[1], x[0].get("page", 0)),
    )
    top = [p for p, score in scored if score > 0][:_MAX_CANDIDATE_PAGES]
    return top if top else pages[:3]


def _compute_confidence(
    steps: list[dict], citations: list[Citation], issues: list[str]
) -> float:
    """Compute a quality-based confidence score for the waterfall extraction.

    Components:
    - Citation coverage  (50 %): fraction of steps whose page was verified
    - Rank continuity    (25 %): no gaps in the sequential priority ranking
    - Completeness       (25 %): found ≥ _MIN_EXPECTED_STEPS priority items
    - Issue penalty      (up to -30 %): unresolvable page citations

    Capped at 0.95 to reflect residual LLM uncertainty.
    """
    n_steps = len(steps)
    if n_steps == 0:
        return 0.0

    citation_coverage = len(citations) / n_steps

    ranks = sorted(s["rank"] for s in steps)
    if len(ranks) > 1:
        gaps = sum(1 for a, b in zip(ranks, ranks[1:]) if b - a > 1)
        rank_continuity = 1.0 - (gaps / (len(ranks) - 1))
    else:
        rank_continuity = 1.0

    completeness = min(n_steps / _MIN_EXPECTED_STEPS, 1.0)
    issue_penalty = min(len(issues) * 0.05, 0.30)

    raw = (
        0.50 * citation_coverage
        + 0.25 * rank_continuity
        + 0.25 * completeness
        - issue_penalty
    )
    return round(max(0.0, min(0.95, raw)), 4)


def _build_prompt(document: str, pages: list[dict], context_hint: str = "") -> str:
    blocks = []
    for p in pages:
        text = (p.get("text", "") or "").strip()
        if text:
            blocks.append(f"[PAGE {p['page']}]\n{text[:2500]}")
    corpus = "\n\n".join(blocks) if blocks else "(no text available)"
    hint_section = f"\nANALYST HINT: {context_hint}\n" if context_hint else ""
    return (
        f"Document: {document}\n"
        f"{hint_section}\n"
        "Extract the COMPLETE priority-of-payments waterfall from the pages below. "
        "RMBS prospectuses typically contain multiple priority cascades — extract ALL of them:\n"
        "  (1) Revenue / Interest Priority of Payments (pre-enforcement)\n"
        "  (2) Principal / Redemption Priority of Payments\n"
        "  (3) Post-Enforcement Priority of Payments\n\n"
        "Return a JSON array where each object represents one waterfall step and has keys:\n"
        "  'rank' (int, global 1-based order across ALL cascades),\n"
        "  'waterfall_type' (str: 'revenue_interest', 'principal_redemption', or 'post_enforcement'),\n"
        "  'beneficiary' (str, who receives the payment),\n"
        "  'amount_basis' (str, how the amount is determined),\n"
        "  'conditions' (str, any conditions or triggers, or 'none'),\n"
        "  'page' (int, the [PAGE n] marker where this step appears),\n"
        "  'excerpt' (str, text copied VERBATIM from that page, max 150 chars).\n\n"
        "Return ONLY the JSON array. Order by cascade (revenue_interest first, then "
        "principal_redemption, then post_enforcement), then by rank within each cascade. "
        "Number ranks continuously from 1 across all cascades.\n\n"
        f"PAGES:\n{corpus}"
    )


def _coerce_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        for key in ("steps", "waterfall", "waterfall_steps", "items"):
            if isinstance(raw.get(key), list):
                return [r for r in raw[key] if isinstance(r, dict)]
        return [raw]
    return []
