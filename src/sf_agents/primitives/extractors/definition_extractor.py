"""Extract formal definitions of named terms from page-keyed document chunks.

This is an LLM-backed primitive. To keep the test-suite offline and the provider
boundary thin, the JSON-LLM function is injected at construction time and
defaults to :func:`sf_agents.primitives._llm.complete_json`.

The extractor pre-filters to candidate pages that mention each term (cheap,
deterministic) and asks the model to return, per term, a definition with the
page number and a verbatim excerpt. Confidence is ``found / requested`` -- a
transparent, defensible signal rather than a model-reported guess.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a meticulous structured-finance analyst. You extract how legal and "
    "servicing documents formally define specific terms. You never invent text: "
    "every excerpt must be copied verbatim from the page you cite."
)


class DefinitionExtractor(BasePrimitive):
    """Extract per-term definitions (definition + page + verbatim excerpt).

    Input args:
        pages (list[dict]): ``[{"page": int, "text": str}, ...]`` from a connector.
        terms (list[str]): The terms whose definitions to extract.
        document (str): Source document name (used for citation ``source``).

    Payload:
        ``{"document": str, "definitions": [{term, definition, page, excerpt}...]}``
    """

    name = "extractor.definitions"
    version = "0.1.0"
    capability = (
        "Given page-keyed document chunks and a list of terms (e.g. arrears, "
        "default, cure), extract each term's formal definition with the page "
        "number and a verbatim excerpt. Confidence = found / requested."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: reference a connector's payload.pages, e.g. {\"$from\": \"<load_step>\", \"path\": \"payload.pages\"}.",
        "terms": "list[str]: the terms to define (literal, e.g. context.terms).",
        "document": "str: source document name; reference the connector's payload.document.",
    }
    outputs = {
        "payload.document": "str: the document name echoed back.",
        "payload.definitions": "list[{term, definition, page, excerpt}]: feed to analyzer.definition_comparator as definitions_a / definitions_b.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm  # lazy: avoid import at module load
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages: list[dict[str, Any]] = inp.get("pages", []) or []
        terms: list[str] = [t for t in (inp.get("terms", []) or []) if str(t).strip()]
        document: str = inp.get("document", "document")
        if not terms:
            return PrimitiveOutput(
                payload={"document": document, "definitions": []},
                confidence=1.0,
                issues=["No terms requested."],
            )

        candidate_pages = self._candidate_pages(pages, terms)
        prompt = self._build_prompt(document, terms, candidate_pages)
        raw = self._llm(prompt, system=_SYSTEM, max_tokens=4096)
        records = self._coerce_records(raw)

        valid_pages = {p["page"]: p["text"] for p in pages}
        definitions: list[dict[str, Any]] = []
        citations: list[Citation] = []
        issues: list[str] = []

        for rec in records:
            term = str(rec.get("term", "")).strip()
            definition = str(rec.get("definition", "")).strip()
            excerpt = str(rec.get("excerpt", "")).strip()
            page = rec.get("page")
            if not term or not definition:
                continue
            entry = {"term": term, "definition": definition, "page": page, "excerpt": excerpt}
            definitions.append(entry)
            # Only cite when the page is real and the excerpt actually appears.
            if isinstance(page, int) and page in valid_pages:
                page_text = valid_pages[page]
                if excerpt and excerpt[:60] not in page_text:
                    issues.append(
                        f"Excerpt for '{term}' not found verbatim on page {page}; "
                        "treating definition as unverified."
                    )
                else:
                    citations.append(
                        Citation(source=document, location=f"page={page}", excerpt=excerpt[:240])
                    )
            else:
                issues.append(f"No resolvable page cited for term '{term}'.")

        found = len({d["term"].lower() for d in definitions})
        requested = len({t.lower() for t in terms})
        confidence = round(found / requested, 4) if requested else 1.0
        missing = sorted({t for t in terms} - {d["term"] for d in definitions})
        if missing:
            issues.append(f"No definition extracted for: {', '.join(missing)}.")

        return PrimitiveOutput(
            payload={"document": document, "definitions": definitions},
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={
                "requested": requested,
                "found": found,
                "candidate_pages": [p["page"] for p in candidate_pages],
            },
        )

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _candidate_pages(
        pages: list[dict[str, Any]], terms: list[str]
    ) -> list[dict[str, Any]]:
        """Pages whose text mentions at least one term (case-insensitive)."""
        lowered = [t.lower() for t in terms]
        hits = [
            p for p in pages
            if any(term in (p.get("text", "") or "").lower() for term in lowered)
        ]
        # Fall back to the first few pages if nothing matched, so the model still
        # has something to work with (e.g. a "Definitions" section with synonyms).
        return hits if hits else pages[:5]

    @staticmethod
    def _build_prompt(
        document: str, terms: list[str], pages: list[dict[str, Any]]
    ) -> str:
        blocks = []
        for p in pages:
            text = (p.get("text", "") or "").strip()
            if text:
                blocks.append(f"[PAGE {p['page']}]\n{text[:4000]}")
        corpus = "\n\n".join(blocks) if blocks else "(no text available)"
        term_list = ", ".join(terms)
        return (
            f"Document: {document}\n\n"
            f"From the pages below, extract the formal definition of each of these "
            f"terms: {term_list}.\n\n"
            "For each term you can find, return an object with keys: 'term', "
            "'definition' (a concise paraphrase), 'page' (the integer page number "
            "shown in the [PAGE n] marker where the definition appears), and "
            "'excerpt' (text copied VERBATIM from that page). Omit terms you cannot "
            "find. Return a JSON array of such objects.\n\n"
            f"PAGES:\n{corpus}"
        )

    @staticmethod
    def _coerce_records(raw: Any) -> list[dict[str, Any]]:
        """Normalise the model reply into a list of dict records."""
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
        if isinstance(raw, dict):
            for key in ("definitions", "results", "items"):
                if isinstance(raw.get(key), list):
                    return [r for r in raw[key] if isinstance(r, dict)]
            return [raw]
        return []
