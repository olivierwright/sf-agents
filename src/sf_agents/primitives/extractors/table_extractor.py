"""Extract tabular data from PDF pages.

PDF text extraction destroys table geometry — columns become jumbled lines.
This primitive uses the LLM to reconstruct table semantics from the raw
text layout, understanding which lines are headers, which are data rows,
and what the relationships between columns mean.

Typical use cases in RMBS/ABS prospectuses:
  - Capital structure table (tranche, principal, rating, interest rate)
  - Pool stratification tables (LTV buckets, geographic breakdown)
  - Performance summary tables (arrears, defaults, prepayments)
  - Credit enhancement table (OC, reserve fund, subordination levels)

Strategies (tried in order, stopping at first success):
  1. Hint-directed (table_hint name → keyword search)
  2. Numeric density scoring (pages with many numbers in columnar layout)
  3. Header-pattern detection (lines that look like column headers)
  4. LLM document scout (finds table by description)
  5. Absence certification
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
)

JsonLLM = Callable[..., Any]

_SYSTEM_EXTRACT = (
    "You are a structured-finance data analyst specialising in PDF table extraction. "
    "Your task is to reconstruct tabular data from raw PDF text. "
    "PDF extraction destroys table geometry — look at the layout, spacing, and repeating "
    "patterns to understand the table structure. "
    "Return the table as a JSON object with 'headers' (list of column names) and "
    "'rows' (list of dicts mapping header→value). "
    "If multiple tables are present, return the one that best matches the table_hint."
)

_SYSTEM_VERIFY = (
    "You are a structured-finance data reviewer. "
    "Determine whether the extracted data forms a real table (consistent columns, "
    "meaningful values) or is a false positive (random numbers, prose, cross-references). "
    "Respond with a single JSON object only."
)


class TableExtractor(BasePrimitive):
    """Extract tabular data from a PDF document.

    Handles the common case where PDF text extraction destroys column alignment.
    Uses LLM to reconstruct the table's semantic structure from raw text.
    """

    name = "extractor.table"
    version = "0.1.0"
    capability = (
        "Extract a named table from a prospectus or PDF (capital structure, pool stats, "
        "performance data, credit enhancement). Reconstructs tabular data destroyed by "
        "PDF text extraction using LLM semantic understanding. Returns headers and rows "
        "with page citations. Uses autonomous retry loop with absence certification. "
        "Input pages from connector.prospectus or connector.pdf_document."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: pages from a connector.",
        "document": "str: source document name.",
        "table_hint": "str: description of the table to find (e.g. 'capital structure table with tranche ratings', 'pool stratification by LTV bucket').",
        "context_hint": "str, optional: page range or section hint.",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.table_name": "str: identified table name/title.",
        "payload.headers": "list[str]: column names.",
        "payload.rows": "list[dict]: data rows as {header: value} dicts.",
        "payload.page": "int: source page number.",
        "payload.absence_certified": "bool: True when exhaustive search confirmed no table.",
        "payload.gap_summary": "str: synthesizer-ready explanation if absent.",
        "payload.discovery_method": "str: which strategy succeeded.",
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
        table_hint: str = str(inp.get("table_hint", "") or "").strip()
        context_hint: str = str(inp.get("context_hint", "") or "").strip()

        if not table_hint:
            return PrimitiveOutput(
                payload=self._empty_payload(document, [], "table_hint is required"),
                citations=[], confidence=0.0, issues=["table_hint is required."],
            )

        page_by_num = {p["page"]: p for p in pages}
        strategies_tried: list[str] = []
        all_attempts: list[tuple[str, dict, int]] = []  # (name, table_data, page_num)
        tried: set[frozenset[int]] = set()

        def try_strategy(name: str, candidate_pages: list[dict]) -> Optional[PrimitiveOutput]:
            page_key = frozenset(p["page"] for p in candidate_pages)
            if page_key in tried:
                return None
            tried.add(page_key)

            table_data, page_num, issues = self._extract_table(document, candidate_pages, table_hint)
            if table_data and table_data.get("headers") and table_data.get("rows"):
                ok, note = self._verify_table(table_data, candidate_pages)
                if ok:
                    conf = _compute_confidence(table_data, issues)
                    if conf >= HIGH_CONFIDENCE:
                        cit = [Citation(
                            source=document,
                            location=f"page={page_num}",
                            excerpt=f"Table: {table_data.get('table_name', table_hint)[:120]}",
                        )] if page_num else []
                        return PrimitiveOutput(
                            payload={
                                "document": document,
                                "table_name": table_data.get("table_name", table_hint),
                                "headers": table_data["headers"],
                                "rows": table_data["rows"],
                                "page": page_num,
                                "absence_certified": False,
                                "gap_summary": "",
                                "discovery_method": name,
                                "strategies_tried": strategies_tried,
                            },
                            citations=cit,
                            confidence=conf,
                            issues=issues,
                            metadata={"rows_found": len(table_data["rows"]), "strategies_tried": strategies_tried},
                        )
                all_attempts.append((name, table_data, page_num))
            return None

        # Strategy 1: hint-directed
        if context_hint:
            hint_pages = pages_from_hint(pages, context_hint, page_by_num)
            if hint_pages:
                strategies_tried.append("hint_directed")
                result = try_strategy("hint_directed", hint_pages)
                if result:
                    return result

        # Strategy 2: numeric density scoring
        density_pages = _numeric_density_score(pages)
        if density_pages:
            strategies_tried.append("numeric_density")
            result = try_strategy("numeric_density", density_pages)
            if result:
                return result

        # Strategy 3: header-pattern detection
        header_pages = _header_pattern_pages(pages, table_hint, page_by_num)
        if header_pages:
            strategies_tried.append("header_pattern")
            result = try_strategy("header_pattern", header_pages)
            if result:
                return result

        # Strategy 4: LLM document scout
        strategies_tried.append("llm_document_scout")
        scout_candidates = llm_document_scout(
            pages, page_by_num, document, f"table: {table_hint}", self._llm, context_hint
        )
        for sname, scout_pages in scout_candidates:
            strategies_tried.append(sname)
            result = try_strategy(sname, scout_pages)
            if result:
                return result

        # Phase 3: best partial
        if all_attempts:
            best_name, best_table, best_page = max(all_attempts, key=lambda x: len(x[1].get("rows", [])))
            conf = _compute_confidence(best_table, []) * PARTIAL_CONFIDENCE_FACTOR
            cit = [Citation(
                source=document,
                location=f"page={best_page}",
                excerpt=f"Table: {best_table.get('table_name', table_hint)[:120]}",
            )] if best_page else []
            return PrimitiveOutput(
                payload={
                    "document": document,
                    "table_name": best_table.get("table_name", table_hint),
                    "headers": best_table.get("headers", []),
                    "rows": best_table.get("rows", []),
                    "page": best_page,
                    "absence_certified": False,
                    "gap_summary": f"Table found via '{best_name}' but could not be fully verified.",
                    "discovery_method": best_name,
                    "strategies_tried": strategies_tried,
                },
                citations=cit,
                confidence=round(conf, 4),
                issues=["Partial result — table verification not passed."],
                metadata={"strategies_tried": strategies_tried},
            )

        # Phase 4: absence certification
        strategies_tried.append("absence_certification")
        absence = certify_absence(pages, document, f"table: {table_hint}", self._llm)

        if absence.get("confident_absent") and absence.get("confidence", 0) >= MIN_ABSENCE_CONFIDENCE:
            explanation = absence.get("explanation", "Table not found.")
            gap = absence.get("gap_summary", explanation)
            return PrimitiveOutput(
                payload=self._empty_payload(document, strategies_tried, explanation, gap, absence_certified=True),
                citations=[],
                confidence=round(absence["confidence"], 4),
                issues=[explanation],
                metadata={"strategies_tried": strategies_tried},
            )

        return PrimitiveOutput(
            payload=self._empty_payload(
                document, strategies_tried,
                "Exhausted all strategies — table may use non-standard formatting.",
            ),
            citations=[], confidence=0.0,
            issues=["No table found after exhausting all strategies."],
            metadata={"strategies_tried": strategies_tried},
        )

    def _extract_table(
        self, document: str, candidate_pages: list[dict], table_hint: str
    ) -> tuple[dict, Optional[int], list[str]]:
        page_blocks = "\n\n".join(
            f"[PAGE {p['page']}]\n{(p.get('text', '') or '').strip()[:4000]}"
            for p in sorted(candidate_pages, key=lambda x: x.get("page", 0))
            if (p.get("text", "") or "").strip()
        )
        prompt = (
            f"Document: {document}\n"
            f"TABLE TO FIND: {table_hint}\n\n"
            "TASK: Locate and reconstruct the table described above from the pages below. "
            "PDF text extraction destroys table layout — use contextual understanding to "
            "identify column headers and data rows from the raw text.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "table_name": str,\n'
            '  "page": int,\n'
            '  "headers": list[str],\n'
            '  "rows": list[dict]\n'
            "}\n\n"
            "If the table is not present, return: "
            '{"table_name": "", "page": null, "headers": [], "rows": []}\n\n'
            f"PAGES:\n{page_blocks}"
        )
        try:
            raw = self._llm(prompt, system=_SYSTEM_EXTRACT, max_tokens=4000)
        except Exception as exc:
            return {}, None, [f"LLM table extraction failed: {exc}"]

        if not isinstance(raw, dict):
            return {}, None, ["Table extraction returned unexpected format."]

        page_num = raw.get("page")
        if not isinstance(page_num, int):
            page_num = None
        return raw, page_num, []

    def _verify_table(self, table_data: dict, candidate_pages: list[dict]) -> tuple[bool, str]:
        headers = table_data.get("headers", [])
        rows = table_data.get("rows", [])
        if len(headers) >= 2 and len(rows) >= 2:
            return True, "fast-path: sufficient columns and rows"

        prompt = (
            f"EXTRACTED TABLE:\n"
            f"Headers: {headers}\n"
            f"Rows (first 5): {rows[:5]}\n\n"
            "Is this a genuine structured table (consistent columns, meaningful values) "
            "or a false positive?\n"
            'Return JSON: {"valid": bool, "confidence": float, "note": str}'
        )
        try:
            result = self._llm(prompt, system=_SYSTEM_VERIFY, max_tokens=200)
            if isinstance(result, dict):
                return bool(result.get("valid", False)), str(result.get("note", ""))
        except Exception:
            pass
        return len(rows) >= 1, "heuristic fallback"

    @staticmethod
    def _empty_payload(
        document: str, strategies_tried: list[str], explanation: str,
        gap_summary: str = "", absence_certified: bool = False,
    ) -> dict:
        return {
            "document": document,
            "table_name": "",
            "headers": [],
            "rows": [],
            "page": None,
            "absence_certified": absence_certified,
            "gap_summary": gap_summary or explanation,
            "discovery_method": "none",
            "strategies_tried": strategies_tried,
        }


# ---------------------------------------------------------------------------
# Page selection strategies
# ---------------------------------------------------------------------------

def _numeric_density_score(pages: list[dict]) -> list[dict]:
    """Score pages by how many numeric values they contain (table signal)."""
    import re as _re
    scored = []
    for p in pages:
        text = p.get("text", "") or ""
        nums = len(_re.findall(r'\b\d[\d,.\s%€$£]+\b', text))
        if nums >= 5:
            scored.append((p, nums))
    scored.sort(key=lambda x: (-x[1], x[0].get("page", 0)))
    return [p for p, _ in scored[:MAX_CANDIDATE_PAGES]]


def _header_pattern_pages(
    pages: list[dict], table_hint: str, page_by_num: dict[int, dict]
) -> list[dict]:
    """Find pages likely to start a table by looking for header-like lines."""
    hint_words = set(table_hint.lower().split())
    scored = []
    for p in pages:
        text = p.get("text", "") or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # Header lines are short, title-cased or ALL CAPS, with many words
        header_score = sum(
            1 for line in lines
            if len(line.split()) >= 2 and len(line) < 80
            and (line.isupper() or line.istitle() or any(w in line.lower() for w in hint_words))
        )
        if header_score >= 2:
            scored.append((p, header_score))
    scored.sort(key=lambda x: (-x[1], x[0].get("page", 0)))
    return [p for p, _ in scored[:MAX_CANDIDATE_PAGES]]


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def _compute_confidence(table_data: dict, issues: list[str]) -> float:
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])
    if not headers or not rows:
        return 0.0
    header_score = min(len(headers) / 3, 1.0)
    row_score = min(len(rows) / 5, 1.0)
    fill_score = (
        sum(1 for r in rows[:10] for v in r.values() if v and str(v).strip())
        / max(len(headers) * min(len(rows), 10), 1)
    )
    issue_penalty = min(len(issues) * 0.05, 0.20)
    raw = 0.30 * header_score + 0.35 * row_score + 0.30 * fill_score - issue_penalty
    return round(max(0.0, min(0.95, raw)), 4)
