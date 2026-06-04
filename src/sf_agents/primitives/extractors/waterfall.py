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

        candidate_pages = _candidate_pages(pages, _KEYWORDS)
        if not candidate_pages:
            return PrimitiveOutput(
                payload={"document": document, "waterfall_steps": []},
                citations=[],
                confidence=0.0,
                issues=["No waterfall-related pages found in document."],
                metadata={"candidate_pages": []},
            )

        prompt = _build_prompt(document, candidate_pages)
        raw = self._llm(prompt, system=_SYSTEM, max_tokens=4096)
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

            if not beneficiary:
                continue

            step = {
                "rank": rank,
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

        n_candidates = len(candidate_pages)
        confidence = round(min(len(steps) / max(n_candidates, 1), 1.0), 4)

        return PrimitiveOutput(
            payload={"document": document, "waterfall_steps": steps},
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={"candidate_pages": [p["page"] for p in candidate_pages], "steps_found": len(steps)},
        )


def _candidate_pages(pages: list[dict], keywords: set[str]) -> list[dict]:
    hits = [
        p for p in pages
        if any(kw in (p.get("text", "") or "").lower() for kw in keywords)
    ]
    return hits if hits else pages[:3]


def _build_prompt(document: str, pages: list[dict]) -> str:
    blocks = []
    for p in pages:
        text = (p.get("text", "") or "").strip()
        if text:
            blocks.append(f"[PAGE {p['page']}]\n{text[:3000]}")
    corpus = "\n\n".join(blocks) if blocks else "(no text available)"
    return (
        f"Document: {document}\n\n"
        "Extract the complete priority-of-payments waterfall from the pages below. "
        "Return a JSON array where each object represents one waterfall step and has keys:\n"
        "  'rank' (int, 1-based priority order),\n"
        "  'beneficiary' (str, who receives the payment),\n"
        "  'amount_basis' (str, how the amount is determined),\n"
        "  'conditions' (str, any conditions or triggers, or 'none'),\n"
        "  'page' (int, the [PAGE n] marker where this step appears),\n"
        "  'excerpt' (str, text copied VERBATIM from that page).\n\n"
        "Return ONLY the JSON array. Order steps by priority rank ascending. "
        "Limit each 'excerpt' field to 150 characters maximum.\n\n"
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
