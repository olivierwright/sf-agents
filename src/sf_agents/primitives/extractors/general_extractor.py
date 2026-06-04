"""General-purpose structured data extractor.

Extracts any set of named fields from PDF pages using a caller-supplied schema.
Uses the same autonomous multi-phase retry loop as WaterfallExtractor:

  Phase 1 — Structural strategies:
    1a. Hint-directed page range
    1b. LLM document scout (locates section by description)
    1c. Keyword density scoring on schema field names
  Phase 2 — Extraction + verification on each candidate set
  Phase 3 — Best partial result (if steps found but not verified)
  Phase 4 — Absence certification

This is the primitive to reach for when the question doesn't match any
domain-specific extractor (waterfall, covenants, definitions) — for example,
"What is the reserve fund floor?", "What are the eligibility criteria?",
"What is the liquidity facility size?".
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ._autonomous_loop import (
    HIGH_CONFIDENCE,
    MAX_CANDIDATE_PAGES,
    MIN_ABSENCE_CONFIDENCE,
    PARTIAL_CONFIDENCE_FACTOR,
    AutonomousExtractionLoop,
    certify_absence,
    llm_document_scout,
    pages_from_hint,
    stratified_sample,
)

JsonLLM = Callable[..., Any]

_SYSTEM_EXTRACT = (
    "You are a structured-finance document analyst. "
    "Extract exactly the fields listed in the schema from the pages provided. "
    "Use verbatim excerpts. Only extract values that are explicitly stated in the text. "
    "Do not infer or estimate values not present in the source pages. "
    "Return a JSON array of extraction records."
)

_SYSTEM_VERIFY = (
    "You are a structured-finance compliance reviewer. "
    "Determine whether extracted records are genuine data values from the document "
    "or false positives (cross-references, examples, risk-factor mentions). "
    "Respond with a single JSON object only."
)


class GeneralExtractor(BasePrimitive):
    """Extract any named fields from a document using a caller-supplied schema.

    The schema is a dict mapping field names to descriptions of what to look for.
    Example::

        schema = {
            "reserve_fund_floor": "Minimum required balance in the reserve fund account",
            "liquidity_facility_size": "Maximum amount available under the liquidity facility",
            "clean_up_call_threshold": "Percentage of outstanding notes triggering the clean-up call",
        }

    The extractor runs an autonomous retry loop, trying multiple page-selection
    strategies, verifying each extraction, and certifying absence if nothing is
    found after exhausting all strategies.
    """

    name = "extractor.general"
    version = "0.1.0"
    capability = (
        "Extract any named fields from a prospectus or PDF using a caller-supplied schema dict. "
        "Uses an autonomous multi-phase retry loop: hint-directed search, LLM document scouting, "
        "keyword density scoring, extraction verification, and absence certification. "
        "Returns per-field records with values, page citations, and verbatim excerpts. "
        "When data is absent after exhaustive search, sets absence_certified=True with a gap explanation. "
        "Use for fields not covered by domain-specific extractors (waterfall, covenants, definitions). "
        "Input pages from connector.prospectus or connector.pdf_document."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: pages from a connector.",
        "document": "str: source document name.",
        "schema": "dict[str, str]: {field_name: field_description} — what to extract and where to find it.",
        "context_hint": "str, optional: page range or section hint from analyst or extractor.locator.",
        "section_hint": "str, optional: plain-English description of the section containing the data.",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.records": "list[{field, value, page, excerpt, confidence}]: extracted field values.",
        "payload.fields_found": "list[str]: field names successfully extracted.",
        "payload.fields_missing": "list[str]: field names not found in document.",
        "payload.absence_certified": "bool: True when exhaustive search confirmed absence.",
        "payload.absence_explanation": "str: why data is absent.",
        "payload.gap_summary": "str: synthesizer-ready gap explanation.",
        "payload.discovery_method": "str: which strategy found the data.",
        "payload.strategies_tried": "list[str]: all strategies attempted.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages: list[dict[str, Any]] = inp.get("pages", []) or []
        document: str = inp.get("document", "document")
        schema: dict[str, str] = inp.get("schema", {}) or {}
        context_hint: str = str(inp.get("context_hint", "") or "").strip()
        section_hint: str = str(inp.get("section_hint", "") or "").strip()

        if not schema:
            return PrimitiveOutput(
                payload=self._empty_payload(document, [], "schema is required"),
                citations=[], confidence=0.0,
                issues=["schema dict is required."],
            )

        page_by_num = {p["page"]: p for p in pages}
        strategies_tried: list[str] = []

        combined_hint = context_hint or section_hint
        target_description = (
            f"{section_hint}: " if section_hint else ""
        ) + ", ".join(f"{k} ({v})" for k, v in list(schema.items())[:5])

        def make_output(name, records, citations, issues, verify_note):
            fields_found = sorted({r["field"] for r in records})
            fields_missing = [f for f in schema if f not in fields_found]
            conf = _compute_confidence(records, citations, issues, schema)
            return PrimitiveOutput(
                payload={
                    "document": document,
                    "records": records,
                    "fields_found": fields_found,
                    "fields_missing": fields_missing,
                    "absence_certified": False,
                    "absence_explanation": "",
                    "gap_summary": "",
                    "discovery_method": name,
                    "strategies_tried": strategies_tried,
                    "verification_note": verify_note,
                },
                citations=citations,
                confidence=conf,
                issues=issues,
                metadata={"records_found": len(records), "strategies_tried": strategies_tried},
            )

        loop = AutonomousExtractionLoop(
            extractor=lambda doc, cands, all_p, hint: self._extract(doc, cands, all_p, schema, hint),
            verifier=lambda records, cands: self._verify(records, cands, schema),
        )

        # Phase 1: structural strategies
        structural = list(_build_structural_strategies(pages, combined_hint, page_by_num, schema))
        strategies_tried.extend(n for n, _ in structural)
        result = loop.run(document, iter(structural), pages, combined_hint, make_output)
        if result:
            return result

        # Phase 2: LLM document scout
        strategies_tried.append("llm_document_scout")
        scout_candidates = llm_document_scout(
            pages, page_by_num, document, target_description, self._llm, combined_hint
        )
        for sname, _ in scout_candidates:
            strategies_tried.append(sname)
        result = loop.run(document, iter(scout_candidates), pages, combined_hint, make_output)
        if result:
            return result

        # Phase 3: best partial
        if loop.best_partial:
            name, records, citations, issues = loop.best_partial
            fields_found = sorted({r["field"] for r in records})
            fields_missing = [f for f in schema if f not in fields_found]
            raw_conf = _compute_confidence(records, citations, issues, schema)
            partial_conf = round(raw_conf * PARTIAL_CONFIDENCE_FACTOR, 4)
            return PrimitiveOutput(
                payload={
                    "document": document,
                    "records": records,
                    "fields_found": fields_found,
                    "fields_missing": fields_missing,
                    "absence_certified": False,
                    "absence_explanation": "",
                    "gap_summary": (
                        f"Partial extraction via '{name}': found {len(fields_found)} of "
                        f"{len(schema)} fields. Missing: {fields_missing}. "
                        "Results could not be fully verified."
                    ),
                    "discovery_method": name,
                    "strategies_tried": strategies_tried,
                },
                citations=citations,
                confidence=partial_conf,
                issues=issues + ["Partial result — verification not passed."],
                metadata={"records_found": len(records), "strategies_tried": strategies_tried},
            )

        # Phase 4: absence certification
        strategies_tried.append("absence_certification")
        absence = certify_absence(pages, document, target_description, self._llm)

        if absence.get("confident_absent") and absence.get("confidence", 0) >= MIN_ABSENCE_CONFIDENCE:
            explanation = absence.get("explanation", "Data not found.")
            gap = absence.get("gap_summary", explanation)
            if absence.get("possible_location"):
                gap += f" Possible location: {absence['possible_location']}"
            return PrimitiveOutput(
                payload=self._empty_payload(document, strategies_tried, explanation, gap_summary=gap, absence_certified=True),
                citations=[],
                confidence=round(absence["confidence"], 4),
                issues=[explanation],
                metadata={"strategies_tried": strategies_tried},
            )

        return PrimitiveOutput(
            payload=self._empty_payload(
                document, strategies_tried,
                "Exhausted all strategies. Document may use non-standard formatting.",
            ),
            citations=[], confidence=0.0,
            issues=["No data found after exhausting all strategies."],
            metadata={"strategies_tried": strategies_tried},
        )

    def _extract(
        self, document: str, candidate_pages: list[dict], all_pages: list[dict],
        schema: dict[str, str], context_hint: str,
    ) -> tuple[list[dict], list[Citation], list[str]]:
        schema_desc = "\n".join(f'  "{k}": {v}' for k, v in schema.items())
        page_blocks = "\n\n".join(
            f"[PAGE {p['page']}]\n{(p.get('text', '') or '').strip()[:3500]}"
            for p in sorted(candidate_pages, key=lambda x: x.get("page", 0))
            if (p.get("text", "") or "").strip()
        )
        hint_line = f"\nANALYST HINT: {context_hint}\n" if context_hint else ""

        prompt = (
            f"Document: {document}{hint_line}\n\n"
            "SCHEMA — fields to extract:\n"
            f"{schema_desc}\n\n"
            "TASK: Find and extract each field from the pages below. "
            "Only extract values explicitly stated in the text. "
            "For each found value return a JSON object:\n"
            '  "field": str (exact key from schema)\n'
            '  "value": str (the extracted value)\n'
            '  "page": int (page number)\n'
            '  "excerpt": str (≤150 chars verbatim from that page)\n'
            '  "confidence": float (0-1, how certain you are this is the right value)\n\n'
            "Return ONLY a JSON array. Empty array [] if nothing found.\n\n"
            f"PAGES:\n{page_blocks}"
        )

        valid_page_nums = {p["page"] for p in all_pages}
        try:
            raw = self._llm(prompt, system=_SYSTEM_EXTRACT, max_tokens=3000)
        except Exception as exc:
            return [], [], [f"LLM extraction failed: {exc}"]

        records: list[dict] = []
        citations: list[Citation] = []
        issues: list[str] = []

        items = raw if isinstance(raw, list) else (raw.get("records", []) if isinstance(raw, dict) else [])
        for item in items:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field", "")).strip()
            value = str(item.get("value", "")).strip()
            if not field or not value or field not in schema:
                continue
            page = item.get("page")
            excerpt = str(item.get("excerpt", "")).strip()
            conf = float(item.get("confidence", 0.5))
            records.append({"field": field, "value": value, "page": page, "excerpt": excerpt, "confidence": conf})
            if isinstance(page, int) and page in valid_page_nums:
                citations.append(Citation(source=document, location=f"page={page}", excerpt=excerpt[:240]))
            else:
                issues.append(f"Field {field!r}: no resolvable page.")

        return records, citations, issues

    def _verify(self, records: list[dict], candidate_pages: list[dict], schema: dict[str, str]) -> tuple[bool, str]:
        if len(records) >= max(1, len(schema) // 2):
            return True, "fast-path: sufficient fields found"

        record_sample = "\n".join(
            f"  {r['field']}: {r['value']!r} (excerpt: {r['excerpt'][:60]!r})"
            for r in records[:15]
        )
        page_sample = "\n\n".join(
            f"[PAGE {p['page']}]\n{(p.get('text', '') or '')[:600]}"
            for p in sorted(candidate_pages, key=lambda x: x.get("page", 0))[:4]
        )
        prompt = (
            f"EXTRACTED RECORDS ({len(records)} total):\n{record_sample}\n\n"
            f"SAMPLE SOURCE PAGES:\n{page_sample}\n\n"
            "Are these extracted values genuine data from the source pages "
            "(not cross-references, not examples, not risk-factor mentions)?\n"
            'Return JSON: {"valid": bool, "confidence": float, "note": str}'
        )
        try:
            result = self._llm(prompt, system=_SYSTEM_VERIFY, max_tokens=200)
            if isinstance(result, dict):
                return bool(result.get("valid", False)), str(result.get("note", ""))
        except Exception:
            pass
        return len(records) > 0, "heuristic fallback"

    @staticmethod
    def _empty_payload(
        document: str,
        strategies_tried: list[str],
        explanation: str,
        gap_summary: str = "",
        absence_certified: bool = False,
    ) -> dict:
        return {
            "document": document,
            "records": [],
            "fields_found": [],
            "fields_missing": [],
            "absence_certified": absence_certified,
            "absence_explanation": explanation,
            "gap_summary": gap_summary or explanation,
            "discovery_method": "none",
            "strategies_tried": strategies_tried,
        }


# ---------------------------------------------------------------------------
# Strategy builders
# ---------------------------------------------------------------------------

def _build_structural_strategies(
    pages: list[dict],
    context_hint: str,
    page_by_num: dict[int, dict],
    schema: dict[str, str],
):
    if context_hint:
        hint_pages = pages_from_hint(pages, context_hint, page_by_num)
        if hint_pages:
            yield ("hint_directed", hint_pages)

    density_pages = _schema_density_score(pages, schema)
    if density_pages:
        yield ("schema_density", density_pages)


def _schema_density_score(pages: list[dict], schema: dict[str, str]) -> list[dict]:
    """Score pages by how many schema field names / keywords appear in text."""
    keywords = set()
    for field, desc in schema.items():
        keywords.update(field.lower().replace("_", " ").split())
        keywords.update(desc.lower().split()[:8])
    keywords = {kw for kw in keywords if len(kw) > 3}

    scored = []
    for p in pages:
        text = (p.get("text", "") or "").lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((p, score))

    scored.sort(key=lambda x: (-x[1], x[0].get("page", 0)))
    return [p for p, _ in scored[:MAX_CANDIDATE_PAGES]]


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def _compute_confidence(
    records: list[dict],
    citations: list[Citation],
    issues: list[str],
    schema: dict[str, str],
) -> float:
    n = len(records)
    if n == 0:
        return 0.0
    schema_coverage = min(n / max(len(schema), 1), 1.0)
    citation_cov = len(citations) / n
    avg_record_conf = sum(r.get("confidence", 0.5) for r in records) / n
    issue_penalty = min(len(issues) * 0.04, 0.20)
    raw = 0.35 * schema_coverage + 0.30 * citation_cov + 0.25 * avg_record_conf - issue_penalty
    return round(max(0.0, min(0.95, raw)), 4)
