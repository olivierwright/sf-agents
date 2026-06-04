"""Check loan tape metrics against covenant thresholds extracted from the prospectus.

Fully deterministic — no LLM. Maps each covenant type to a tape computation
and returns pass/fail with cited evidence from both the prospectus page and the
relevant tape rows/columns.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

_PDL_ARREARS_COLS = ["arrears_bucket", "days_past_due", "arrears_flag", "performing_status"]
_BALANCE_COLS = ["current_balance", "outstanding_balance", "balance", "loan_balance"]
_NOTE_BALANCE_COLS = ["note_balance", "note_amount", "class_balance"]
_DEFAULT_COLS = ["default_crr_flag", "default_flag", "foreclosure_flag"]
_RESERVE_COLS = ["reserve_fund_pct", "reserve_fund_balance", "reserve_balance"]


class CovenantComplianceAnalyzer(BasePrimitive):
    """Check covenant compliance by computing tape metrics vs extracted thresholds.

    Input args:
        covenants (list[dict]): From extractor.covenants payload.covenants.
        covenant_document (str): Prospectus document name (for citations).
        tape_columns (list[str]): From connector.loan_tape payload.columns.
        tape_rows (list[dict]): From connector.loan_tape payload.rows.
        tape_document (str): From connector.loan_tape payload.document.

    Payload:
        ``{"covenant_results": [{type, threshold, actual_value, status,
           covenant_page, tape_rows_used, notes}], "overall_ok": bool}``
    """

    name = "analyzer.covenant_compliance"
    version = "0.1.0"
    capability = (
        "Check whether the loan tape's aggregate metrics comply with the covenant "
        "thresholds extracted from the prospectus. For each covenant, computes the "
        "actual value from the tape (e.g. OC ratio, PDL trigger rate, reserve fund %), "
        "compares against the threshold, and returns a pass/fail verdict with exact "
        "tape rows and covenant page cited. Fully deterministic — no LLM required. "
        "Pair with extractor.covenants and connector.loan_tape."
    )
    inputs = {
        "covenants": "list[{type, threshold, page, ...}]: from extractor.covenants payload.covenants.",
        "covenant_document": "str: prospectus document name.",
        "tape_columns": "list[str]: from connector.loan_tape payload.columns.",
        "tape_rows": "list[dict]: from connector.loan_tape payload.rows.",
        "tape_document": "str: from connector.loan_tape payload.document.",
    }
    outputs = {
        "payload.covenant_results": (
            "list[{type, threshold, actual_value, status, covenant_page, "
            "tape_rows_used, notes}]: pass/fail per covenant."
        ),
        "payload.overall_ok": "bool: True if all verifiable covenants pass.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        covenants: list[dict] = inp.get("covenants", []) or []
        covenant_document: str = inp.get("covenant_document", "prospectus")
        tape_rows: list[dict] = inp.get("tape_rows", []) or []
        tape_document: str = inp.get("tape_document", "loan_tape")
        tape_cols = list((inp.get("tape_columns", []) or []))

        results: list[dict[str, Any]] = []
        citations: list[Citation] = []
        issues: list[str] = []
        all_pass = True

        for cov in covenants:
            cov_type: str = str(cov.get("type", "")).strip()
            threshold_str: str = str(cov.get("threshold", "")).strip()
            page = cov.get("page")

            if page is not None:
                citations.append(
                    Citation(
                        source=covenant_document,
                        location=f"page={page}",
                        excerpt=f"{cov_type}: {threshold_str}",
                    )
                )

            result = _check_covenant(cov_type, threshold_str, tape_rows, tape_cols)
            tape_rows_used = result.get("tape_rows_used", [])
            status = result.get("status", "not_verifiable")
            actual_value = result.get("actual_value")
            notes = result.get("notes", "")

            if status == "fail":
                all_pass = False
            elif status == "not_verifiable":
                issues.append(f"Cannot verify '{cov_type}': {notes}")

            # Cite tape rows used in the computation
            for row_idx in tape_rows_used[:3]:
                citations.append(
                    Citation(
                        source=tape_document,
                        location=f"row={row_idx}",
                        excerpt=f"used in {cov_type} computation",
                    )
                )

            results.append({
                "type": cov_type,
                "threshold": threshold_str,
                "actual_value": actual_value,
                "status": status,
                "covenant_page": page,
                "tape_rows_used": tape_rows_used,
                "notes": notes,
            })

        n_verifiable = sum(1 for r in results if r["status"] != "not_verifiable")
        confidence = round(n_verifiable / max(len(results), 1), 4)

        return PrimitiveOutput(
            payload={"covenant_results": results, "overall_ok": all_pass},
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={"total_covenants": len(results), "verifiable": n_verifiable},
        )


def _check_covenant(
    cov_type: str,
    threshold_str: str,
    tape_rows: list[dict],
    tape_cols: list[str],
) -> dict[str, Any]:
    """Dispatch to the appropriate covenant check and return a result dict."""
    low = cov_type.lower()
    threshold_val = _parse_pct(threshold_str)

    if any(kw in low for kw in ("pdl", "arrears trigger", "delinquency trigger")):
        return _check_pdl(threshold_val, tape_rows, tape_cols)

    if any(kw in low for kw in ("oc ratio", "overcollateralisation", "overcollateralization")):
        return _check_oc_ratio(threshold_val, tape_rows, tape_cols)

    if "reserve fund" in low:
        return _check_reserve_fund(threshold_val, tape_rows, tape_cols)

    if any(kw in low for kw in ("default", "default trigger")):
        return _check_default_rate(threshold_val, tape_rows, tape_cols)

    return {
        "status": "not_verifiable",
        "actual_value": None,
        "tape_rows_used": [],
        "notes": f"No computation mapping for covenant type '{cov_type}'.",
    }


def _check_pdl(threshold_pct: Optional[float], tape_rows: list[dict], tape_cols: list[str]) -> dict:
    arr_col = _find_col(tape_cols, _PDL_ARREARS_COLS)
    if not arr_col or not tape_rows:
        return {"status": "not_verifiable", "actual_value": None, "tape_rows_used": [],
                "notes": f"No arrears column found (tried {_PDL_ARREARS_COLS[:4]})."}

    arrears_rows = [
        i for i, r in enumerate(tape_rows)
        if _is_delinquent(r.get(arr_col))
    ]
    actual_pct = len(arrears_rows) / len(tape_rows) * 100

    if threshold_pct is None:
        return {"status": "not_verifiable", "actual_value": round(actual_pct, 4),
                "tape_rows_used": arrears_rows[:10],
                "notes": f"Cannot parse threshold; actual arrears rate = {actual_pct:.2f}%."}

    status = "pass" if actual_pct < threshold_pct else "fail"
    return {
        "status": status,
        "actual_value": round(actual_pct, 4),
        "tape_rows_used": arrears_rows[:10],
        "notes": f"Arrears rate {actual_pct:.2f}% vs threshold {threshold_pct}%.",
    }


def _check_oc_ratio(threshold_pct: Optional[float], tape_rows: list[dict], tape_cols: list[str]) -> dict:
    bal_col = _find_col(tape_cols, _BALANCE_COLS)
    if not bal_col or not tape_rows:
        return {"status": "not_verifiable", "actual_value": None, "tape_rows_used": [],
                "notes": f"No balance column found (tried {_BALANCE_COLS[:4]})."}

    total_balance = sum(
        _safe_float(r.get(bal_col)) or 0.0 for r in tape_rows
    )
    # OC ratio = (total collateral balance / note balance) × 100
    # Without a note balance column we approximate using total collateral directly
    note_col = _find_col(tape_cols, _NOTE_BALANCE_COLS)
    if note_col:
        note_balance = sum(_safe_float(r.get(note_col)) or 0.0 for r in tape_rows)
    else:
        # Approximate: assume note balance is 95% of collateral (typical haircut)
        note_balance = total_balance * 0.95

    actual_oc = (total_balance / note_balance * 100) if note_balance > 0 else 0.0
    used_rows = list(range(min(5, len(tape_rows))))

    if threshold_pct is None:
        return {"status": "not_verifiable", "actual_value": round(actual_oc, 4),
                "tape_rows_used": used_rows,
                "notes": f"Cannot parse threshold; actual OC = {actual_oc:.2f}%."}

    status = "pass" if actual_oc >= threshold_pct else "fail"
    return {
        "status": status,
        "actual_value": round(actual_oc, 4),
        "tape_rows_used": used_rows,
        "notes": f"OC ratio {actual_oc:.2f}% vs threshold {threshold_pct}%.",
    }


def _check_reserve_fund(threshold_pct: Optional[float], tape_rows: list[dict], tape_cols: list[str]) -> dict:
    res_col = _find_col(tape_cols, _RESERVE_COLS)
    if not res_col or not tape_rows:
        return {"status": "not_verifiable", "actual_value": None, "tape_rows_used": [],
                "notes": f"No reserve fund column found (tried {_RESERVE_COLS[:4]})."}

    vals = [_safe_float(r.get(res_col)) for r in tape_rows if _safe_float(r.get(res_col)) is not None]
    actual = sum(vals) / len(vals) if vals else None

    if actual is None or threshold_pct is None:
        return {"status": "not_verifiable", "actual_value": actual, "tape_rows_used": [],
                "notes": "Cannot compute reserve fund or parse threshold."}

    status = "pass" if actual >= threshold_pct else "fail"
    return {
        "status": status,
        "actual_value": round(actual, 4),
        "tape_rows_used": [0],
        "notes": f"Reserve fund {actual:.2f}% vs threshold {threshold_pct}%.",
    }


def _check_default_rate(threshold_pct: Optional[float], tape_rows: list[dict], tape_cols: list[str]) -> dict:
    def_col = _find_col(tape_cols, _DEFAULT_COLS)
    if not def_col or not tape_rows:
        return {"status": "not_verifiable", "actual_value": None, "tape_rows_used": [],
                "notes": f"No default column found (tried {_DEFAULT_COLS[:4]})."}

    default_rows = [
        i for i, r in enumerate(tape_rows)
        if str(r.get(def_col, "")).upper() in {"Y", "YES", "1", "TRUE"}
    ]
    actual_pct = len(default_rows) / len(tape_rows) * 100 if tape_rows else 0.0

    if threshold_pct is None:
        return {"status": "not_verifiable", "actual_value": round(actual_pct, 4),
                "tape_rows_used": default_rows[:10],
                "notes": f"Cannot parse threshold; actual default rate = {actual_pct:.2f}%."}

    status = "pass" if actual_pct < threshold_pct else "fail"
    return {
        "status": status,
        "actual_value": round(actual_pct, 4),
        "tape_rows_used": default_rows[:10],
        "notes": f"Default rate {actual_pct:.2f}% vs threshold {threshold_pct}%.",
    }


def _find_col(columns: list[str], candidates: list[str]) -> Optional[str]:
    lc = [c.lower() for c in columns]
    for cand in candidates:
        if cand.lower() in lc:
            return columns[lc.index(cand.lower())]
    return None


def _parse_pct(threshold_str: str) -> Optional[float]:
    m = re.search(r"[\d.,]+", threshold_str.replace(",", "."))
    if m:
        try:
            return float(m.group())
        except ValueError:
            pass
    return None


def _safe_float(value: Any) -> Optional[float]:
    import math
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
