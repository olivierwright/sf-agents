"""Extract covenant triggers and test thresholds from prospectus pages.

LLM-backed. Pre-filters pages containing covenant keywords before prompting
the model. All threshold values must be verbatim from cited pages.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a structured-finance analyst specialising in covenant mechanics. "
    "Extract covenant triggers and test thresholds from the provided prospectus pages. "
    "Never invent values: all thresholds must be copied verbatim from the cited page."
)

_KEYWORDS = {"pdl", "overcollateralisation", "oc test", "oc ratio", "reserve fund",
             "interest coverage", "trigger", "covenant", "performance test"}


class CovenantExtractor(BasePrimitive):
    """Extract covenant triggers and thresholds from prospectus pages.

    Input args:
        pages (list[dict]): ``[{"page": int, "text": str}, ...]`` from a connector.
        document (str): Source document name (for citations).
        covenant_types (list[str], optional): Filter to specific types.

    Payload:
        ``{"document": str, "covenants": [{type, threshold, test_frequency,
           breach_consequence, page, excerpt}, ...]}``
    """

    name = "extractor.covenants"
    version = "0.1.0"
    capability = (
        "Extract covenant triggers (PDL triggers, reserve fund requirements, OC ratios, "
        "interest coverage tests) from prospectus pages. Returns each covenant with its "
        "type, threshold value, test frequency, breach consequence, source page, and a "
        "verbatim excerpt. Use connector.prospectus to obtain the pages input."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: reference connector.prospectus payload.pages.",
        "document": "str: source document name; reference connector.prospectus payload.document.",
        "covenant_types": "list[str], optional: filter to specific types e.g. ['PDL', 'OC ratio'].",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.covenants": (
            "list[{type:str, threshold:str, test_frequency:str, breach_consequence:str, "
            "page:int, excerpt:str}]: extracted covenants."
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
        covenant_types: list[str] = inp.get("covenant_types", []) or []

        candidate_pages = _candidate_pages(pages, _KEYWORDS)
        if not candidate_pages:
            return PrimitiveOutput(
                payload={"document": document, "covenants": []},
                citations=[],
                confidence=0.0,
                issues=["No covenant-related pages found in document."],
                metadata={"candidate_pages": []},
            )

        prompt = _build_prompt(document, candidate_pages, covenant_types)
        raw = self._llm(prompt, system=_SYSTEM, max_tokens=4096)
        records = _coerce_records(raw)

        valid_pages = {p["page"]: p["text"] for p in pages}
        covenants: list[dict[str, Any]] = []
        citations: list[Citation] = []
        issues: list[str] = []

        for rec in records:
            cov_type = str(rec.get("type", "")).strip()
            threshold = str(rec.get("threshold", "")).strip()
            test_freq = str(rec.get("test_frequency", "")).strip()
            breach = str(rec.get("breach_consequence", "")).strip()
            excerpt = str(rec.get("excerpt", "")).strip()
            page = rec.get("page")

            if not cov_type or not threshold:
                continue

            if covenant_types:
                if not any(ct.lower() in cov_type.lower() for ct in covenant_types):
                    continue

            entry = {
                "type": cov_type,
                "threshold": threshold,
                "test_frequency": test_freq,
                "breach_consequence": breach,
                "page": page,
                "excerpt": excerpt,
            }
            covenants.append(entry)

            if isinstance(page, int) and page in valid_pages:
                citations.append(
                    Citation(source=document, location=f"page={page}", excerpt=excerpt[:240])
                )
            else:
                issues.append(f"Covenant '{cov_type}': no resolvable page cited.")

        n_candidates = len(candidate_pages)
        confidence = round(min(len(covenants) / max(n_candidates, 1), 1.0), 4)

        return PrimitiveOutput(
            payload={"document": document, "covenants": covenants},
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={
                "candidate_pages": [p["page"] for p in candidate_pages],
                "covenants_found": len(covenants),
            },
        )


def _candidate_pages(pages: list[dict], keywords: set[str]) -> list[dict]:
    hits = [
        p for p in pages
        if any(kw in (p.get("text", "") or "").lower() for kw in keywords)
    ]
    return hits if hits else pages[:3]


def _build_prompt(document: str, pages: list[dict], covenant_types: list[str]) -> str:
    blocks = []
    for p in pages:
        text = (p.get("text", "") or "").strip()
        if text:
            blocks.append(f"[PAGE {p['page']}]\n{text[:4000]}")
    corpus = "\n\n".join(blocks) if blocks else "(no text available)"
    type_filter = (
        f"Focus only on these covenant types: {', '.join(covenant_types)}.\n"
        if covenant_types else ""
    )
    return (
        f"Document: {document}\n\n"
        f"{type_filter}"
        "Extract all covenant triggers and performance tests from the pages below. "
        "Return a JSON array where each object has keys:\n"
        "  'type' (str, e.g. 'PDL trigger', 'OC ratio test', 'reserve fund'),\n"
        "  'threshold' (str, the numeric or percentage threshold, verbatim),\n"
        "  'test_frequency' (str, e.g. 'monthly', 'quarterly'),\n"
        "  'breach_consequence' (str, what happens if the test fails),\n"
        "  'page' (int, the [PAGE n] marker where this covenant appears),\n"
        "  'excerpt' (str, text copied VERBATIM from that page).\n\n"
        "Return ONLY the JSON array.\n\n"
        f"PAGES:\n{corpus}"
    )


def _coerce_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        for key in ("covenants", "triggers", "tests", "items"):
            if isinstance(raw.get(key), list):
                return [r for r in raw[key] if isinstance(r, dict)]
        return [raw]
    return []
