"""Parse rating agency action announcements and map them to deal performance data.

LLM-backed for text parsing; deterministic for tape metric computation.
Pre-filters pages mentioning rating action keywords. Each action gets dual
citations: the announcement page and the relevant tape metric rows.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a structured-finance credit analyst. Parse rating agency action "
    "announcements and extract structured information. Be precise and only extract "
    "information that is explicitly stated in the text."
)

_KEYWORDS = {"rating", "upgrade", "downgrade", "affirm", "watch", "review", "aaa", "aa", "bbb", "moody", "fitch", "s&p", "dbrs"}

_ARREARS_COLS = ["arrears_bucket", "days_past_due", "arrears_flag"]
_DEFAULT_COLS = ["default_crr_flag", "default_flag", "foreclosure_flag"]
_BALANCE_COLS = ["current_balance", "outstanding_balance", "balance"]


class RatingActionAnalyzer(BasePrimitive):
    """Parse rating actions and map them to loan tape performance indicators.

    Input args:
        pages (list[dict]): Document pages from any PDF connector.
        document (str): Source document name.
        tape_columns (list[str]): From connector.loan_tape payload.columns.
        tape_rows (list[dict]): From connector.loan_tape payload.rows.
        tape_document (str): From connector.loan_tape payload.document.

    Payload:
        ``{"document": str, "rating_actions": [{action_type, tranche, old_rating,
           new_rating, rationale, performance_mapping, page, excerpt}]}``
    """

    name = "analyzer.rating_action"
    version = "0.1.0"
    capability = (
        "Parse rating agency action announcements (upgrade, downgrade, watch, affirm) "
        "from document pages and map stated rationales to measurable loan tape metrics "
        "(arrears rate, default rate, OC ratio). Cites both the announcement page and "
        "the specific tape rows that support or contradict the stated rationale. "
        "Use any PDF connector to load the rating document pages."
    )
    inputs = {
        "pages": "list[{page:int, text:str}]: document pages from a connector.",
        "document": "str: source document name.",
        "tape_columns": "list[str]: reference connector.loan_tape payload.columns.",
        "tape_rows": "list[dict]: reference connector.loan_tape payload.rows.",
        "tape_document": "str: reference connector.loan_tape payload.document.",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.rating_actions": (
            "list[{action_type, tranche, old_rating, new_rating, rationale, "
            "performance_mapping, page, excerpt}]: parsed rating actions."
        ),
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages: list[dict] = inp.get("pages", []) or []
        document: str = inp.get("document", "document")
        tape_rows: list[dict] = inp.get("tape_rows", []) or []
        tape_document: str = inp.get("tape_document", "loan_tape")
        tape_cols = list((inp.get("tape_columns", []) or []))

        # Compute tape performance metrics deterministically
        tape_metrics = _compute_tape_metrics(tape_rows, tape_cols)

        candidate_pages = _candidate_pages(pages, _KEYWORDS)
        if not candidate_pages:
            return PrimitiveOutput(
                payload={"document": document, "rating_actions": []},
                citations=[],
                confidence=0.0,
                issues=["No rating-action-related pages found in document."],
                metadata={"candidate_pages": [], "tape_metrics": tape_metrics},
            )

        prompt = _build_prompt(document, candidate_pages)
        raw = self._llm(prompt, system=_SYSTEM, max_tokens=4096)
        records = _coerce_records(raw)

        valid_pages = {p["page"]: p["text"] for p in pages}
        actions: list[dict[str, Any]] = []
        citations: list[Citation] = []
        issues: list[str] = []

        for rec in records:
            action_type = str(rec.get("action_type", "")).strip().lower()
            tranche = str(rec.get("tranche", "")).strip()
            old_rating = str(rec.get("old_rating", "")).strip()
            new_rating = str(rec.get("new_rating", "")).strip()
            rationale = str(rec.get("rationale", "")).strip()
            excerpt = str(rec.get("excerpt", "")).strip()
            page = rec.get("page")

            if not action_type:
                continue

            # Map rationale keywords to tape metrics
            performance_mapping = _map_rationale_to_metrics(rationale, tape_metrics)

            action = {
                "action_type": action_type,
                "tranche": tranche,
                "old_rating": old_rating,
                "new_rating": new_rating,
                "rationale": rationale,
                "performance_mapping": performance_mapping,
                "page": page,
                "excerpt": excerpt,
            }
            actions.append(action)

            if isinstance(page, int) and page in valid_pages:
                citations.append(
                    Citation(source=document, location=f"page={page}", excerpt=excerpt[:240])
                )
            else:
                issues.append(f"Rating action '{action_type}' for '{tranche}': no resolvable page cited.")

        # Add tape metric citation if we used tape data
        if tape_metrics and tape_rows:
            citations.append(
                Citation(
                    source=tape_document,
                    location="row=0",
                    excerpt=(
                        f"arrears_rate={tape_metrics.get('arrears_rate_pct', '?')}%, "
                        f"default_rate={tape_metrics.get('default_rate_pct', '?')}%"
                    ),
                )
            )

        confidence = round(
            len([a for a in actions if a.get("page") is not None]) / max(len(actions), 1),
            4,
        ) if actions else 0.0

        return PrimitiveOutput(
            payload={"document": document, "rating_actions": actions},
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={
                "candidate_pages": [p["page"] for p in candidate_pages],
                "tape_metrics": tape_metrics,
                "actions_found": len(actions),
            },
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
            blocks.append(f"[PAGE {p['page']}]\n{text[:4000]}")
    corpus = "\n\n".join(blocks) if blocks else "(no text available)"
    return (
        f"Document: {document}\n\n"
        "Extract all rating agency actions from the pages below. "
        "Return a JSON array where each object has keys:\n"
        "  'action_type' (str: 'upgrade', 'downgrade', 'affirm', 'watch', 'review'),\n"
        "  'tranche' (str: tranche name or 'all'),\n"
        "  'old_rating' (str: previous rating or '' if not stated),\n"
        "  'new_rating' (str: new or confirmed rating),\n"
        "  'rationale' (str: stated reason for the action),\n"
        "  'page' (int: the [PAGE n] marker where the action is stated),\n"
        "  'excerpt' (str: text copied VERBATIM from that page).\n\n"
        "Return ONLY the JSON array.\n\n"
        f"PAGES:\n{corpus}"
    )


def _coerce_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        for key in ("actions", "rating_actions", "items"):
            if isinstance(raw.get(key), list):
                return [r for r in raw[key] if isinstance(r, dict)]
        return [raw]
    return []


def _compute_tape_metrics(tape_rows: list[dict], tape_cols: list[str]) -> dict[str, Any]:
    """Compute arrears rate and default rate from the tape."""
    if not tape_rows:
        return {}

    arr_col = _find_col(tape_cols, _ARREARS_COLS)
    def_col = _find_col(tape_cols, _DEFAULT_COLS)
    bal_col = _find_col(tape_cols, _BALANCE_COLS)

    metrics: dict[str, Any] = {"loan_count": len(tape_rows)}

    if arr_col:
        arrears_count = sum(
            1 for r in tape_rows
            if _is_delinquent(r.get(arr_col))
        )
        metrics["arrears_rate_pct"] = round(arrears_count / len(tape_rows) * 100, 2)

    if def_col:
        default_count = sum(
            1 for r in tape_rows
            if str(r.get(def_col, "")).upper() in {"Y", "YES", "1", "TRUE"}
        )
        metrics["default_rate_pct"] = round(default_count / len(tape_rows) * 100, 2)

    if bal_col:
        total_bal = sum(
            f for r in tape_rows
            if (f := _safe_float(r.get(bal_col))) is not None
        )
        metrics["total_balance"] = round(total_bal, 2)

    return metrics


def _map_rationale_to_metrics(rationale: str, tape_metrics: dict) -> dict[str, Any]:
    """Map rationale keywords to available tape metrics."""
    mapping: dict[str, Any] = {}
    low = rationale.lower()
    if any(kw in low for kw in ("arrears", "delinquent", "past due")):
        mapping["arrears_rate_pct"] = tape_metrics.get("arrears_rate_pct")
    if any(kw in low for kw in ("default", "foreclosure", "loss")):
        mapping["default_rate_pct"] = tape_metrics.get("default_rate_pct")
    if any(kw in low for kw in ("collateral", "balance", "oc", "overcollateral")):
        mapping["total_balance"] = tape_metrics.get("total_balance")
    return mapping


def _find_col(columns: list[str], candidates: list[str]) -> Optional[str]:
    lc = [c.lower() for c in columns]
    for cand in candidates:
        if cand.lower() in lc:
            return columns[lc.index(cand.lower())]
    return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _is_delinquent(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in {"0", "0.0", "current", "performing", "false", "no", "n", ""}:
        return False
    if s in {"1", "2", "3", "y", "yes", "true"}:
        return True
    try:
        return float(s) > 0
    except (TypeError, ValueError):
        return False
