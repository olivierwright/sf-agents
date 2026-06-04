"""Detect cashflow anomalies by comparing remittance actuals against loan tape predictions.

Algorithm:
1. Compute expected per-period collection from loan tape (balance × rate / 12).
2. For each remittance period, compute deviation from expected.
3. Flag periods where |Z-score| exceeds threshold (default 2.0).
4. Ask LLM to narrate flagged periods (seasonal, prepayment, etc.).

Citations ground every flagged remittance row and the tape baseline.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a structured-finance cashflow analyst. For each flagged period below, "
    "provide a concise plain-English rationale for the cashflow anomaly. "
    "Possible reasons include seasonal prepayment patterns, arrears spikes, "
    "interest rate resets, or data collection issues. Be specific but brief."
)

_COLLECTION_COLS = ["period_collections", "actual_collections", "collections", "total_collections"]
_BALANCE_COLS = ["current_balance", "outstanding_balance", "balance", "loan_balance"]
_RATE_COLS = ["current_interest_rate_pct", "interest_rate", "rate_pct", "coupon_rate"]


class CashflowAnomalyAnalyzer(BasePrimitive):
    """Compare remittance cashflows against loan tape predictions and flag outliers.

    Input args:
        remittance_columns (list[str]): Column names from remittance connector.
        remittance_rows (list[dict]): Rows from remittance connector.
        remittance_document (str): File name from remittance connector.
        tape_columns (list[str]): Column names from loan tape connector.
        tape_rows (list[dict]): Rows from loan tape connector.
        tape_document (str): File name from loan tape connector.
        zscore_threshold (float, optional): Anomaly detection threshold (default 2.0).
        collection_column (str, optional): Override remittance column for collections.

    Payload:
        ``{"anomalies": [{period, expected, actual, deviation_pct, zscore,
           remittance_row, rationale}], "summary": {total_periods, anomaly_count,
           max_deviation_pct}}``
    """

    name = "analyzer.cashflow_anomaly"
    version = "0.1.0"
    capability = (
        "Compare expected cashflows (derived from loan tape balances and interest rates) "
        "against actual period cashflows from a remittance file. Flags periods where the "
        "absolute deviation exceeds a Z-score threshold (default 2.0). Returns anomalous "
        "periods with deterministically computed figures and an LLM-narrated rationale. "
        "Requires connector.remittance_file and connector.loan_tape outputs."
    )
    inputs = {
        "remittance_columns": "list[str]: reference connector.remittance_file payload.columns.",
        "remittance_rows": "list[dict]: reference connector.remittance_file payload.rows.",
        "remittance_document": "str: reference connector.remittance_file payload.document.",
        "tape_columns": "list[str]: reference connector.loan_tape payload.columns.",
        "tape_rows": "list[dict]: reference connector.loan_tape payload.rows.",
        "tape_document": "str: reference connector.loan_tape payload.document.",
        "zscore_threshold": "float, optional: anomaly detection threshold (default 2.0).",
        "collection_column": "str, optional: override the remittance column for period collections.",
    }
    outputs = {
        "payload.anomalies": (
            "list[{period, expected, actual, deviation_pct, zscore, remittance_row, rationale}]: "
            "flagged anomalous periods."
        ),
        "payload.summary": (
            "{total_periods, anomaly_count, max_deviation_pct, expected_per_period}: "
            "high-level statistics."
        ),
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        remittance_rows: list[dict] = inp.get("remittance_rows", []) or []
        tape_rows: list[dict] = inp.get("tape_rows", []) or []
        remittance_document: str = inp.get("remittance_document", "remittance")
        tape_document: str = inp.get("tape_document", "loan_tape")
        threshold: float = float(inp.get("zscore_threshold", 2.0))
        collection_col_override: str = inp.get("collection_column", "") or ""

        issues: list[str] = []

        # Determine which column holds period collections
        rem_cols = list((inp.get("remittance_columns", []) or []))
        collection_col = _find_col(
            rem_cols,
            [collection_col_override] if collection_col_override else _COLLECTION_COLS,
        )
        if not collection_col:
            return PrimitiveOutput(
                payload={"anomalies": [], "summary": {}},
                citations=[],
                confidence=0.0,
                issues=[f"No collection column found in {remittance_document}. "
                        f"Available: {rem_cols[:10]}. Use collection_column to override."],
                metadata={},
            )

        # Compute expected cashflow from tape (balance × rate / 12 summed across loans)
        tape_cols = list((inp.get("tape_columns", []) or []))
        balance_col = _find_col(tape_cols, _BALANCE_COLS)
        rate_col = _find_col(tape_cols, _RATE_COLS)

        expected_per_period = 0.0
        if balance_col and rate_col and tape_rows:
            for row in tape_rows:
                bal = _safe_float(row.get(balance_col))
                rate = _safe_float(row.get(rate_col))
                if bal is not None and rate is not None:
                    expected_per_period += bal * (rate / 100.0) / 12.0
            if expected_per_period == 0.0:
                issues.append("Expected cashflow computed as zero; check balance/rate columns.")
        else:
            issues.append(
                f"Cannot compute expected cashflow: balance_col={balance_col!r}, "
                f"rate_col={rate_col!r}. Anomaly detection skipped."
            )
            return PrimitiveOutput(
                payload={"anomalies": [], "summary": {"total_periods": len(remittance_rows)}},
                citations=[],
                confidence=0.8,
                issues=issues,
                metadata={},
            )

        # Compute actuals and deviations
        actuals: list[float] = []
        period_labels: list[str] = []
        for row in remittance_rows:
            val = _safe_float(row.get(collection_col))
            if val is not None:
                actuals.append(val)
                period_labels.append(_period_label(row))

        if not actuals:
            issues.append(f"All rows in {collection_col!r} have non-numeric values.")
            return PrimitiveOutput(
                payload={"anomalies": [], "summary": {}},
                citations=[],
                confidence=0.0,
                issues=issues,
                metadata={},
            )

        deviations = [(a - expected_per_period) / expected_per_period for a in actuals]

        if len(deviations) < 2:
            mean_dev, std_dev = deviations[0], 0.0
        else:
            mean_dev = statistics.mean(deviations)
            std_dev = statistics.stdev(deviations)

        flagged_indices: list[int] = []
        for i, dev in enumerate(deviations):
            zscore = (dev - mean_dev) / std_dev if std_dev > 0 else 0.0
            if abs(zscore) >= threshold:
                flagged_indices.append(i)

        citations: list[Citation] = [
            Citation(
                source=tape_document,
                location="row=0",
                excerpt=f"expected_per_period={expected_per_period:.2f} (from {len(tape_rows)} loans)",
            )
        ]

        # Narrate flagged periods with LLM
        rationales: dict[int, str] = {}
        if flagged_indices:
            flagged_summary = [
                {"period": period_labels[i], "actual": actuals[i],
                 "expected": expected_per_period,
                 "deviation_pct": round(deviations[i] * 100, 2)}
                for i in flagged_indices
            ]
            prompt = (
                f"The following cashflow periods from '{remittance_document}' "
                f"are statistical anomalies (Z-score ≥ {threshold}):\n"
                f"{flagged_summary}\n\n"
                "For each period, return a JSON array of objects with keys "
                "'period' and 'rationale' (one or two sentences)."
            )
            try:
                raw = self._llm(prompt, system=_SYSTEM, max_tokens=1024)
                narrations = raw if isinstance(raw, list) else []
                narration_map = {
                    str(n.get("period", "")): str(n.get("rationale", ""))
                    for n in narrations if isinstance(n, dict)
                }
                for i in flagged_indices:
                    rationales[i] = narration_map.get(period_labels[i], "")
            except Exception:  # noqa: BLE001
                issues.append("LLM narration failed; anomalies returned without rationale.")

        anomalies: list[dict[str, Any]] = []
        for i in flagged_indices:
            dev = deviations[i]
            zscore = (dev - mean_dev) / std_dev if std_dev > 0 else 0.0
            anomalies.append({
                "period": period_labels[i],
                "expected": round(expected_per_period, 2),
                "actual": round(actuals[i], 2),
                "deviation_pct": round(dev * 100, 2),
                "zscore": round(zscore, 3),
                "remittance_row": i,
                "rationale": rationales.get(i, ""),
            })
            citations.append(
                Citation(
                    source=remittance_document,
                    location=f"row={i}",
                    excerpt=f"period={period_labels[i]}, actual={actuals[i]:.2f}",
                )
            )

        max_dev = max((abs(d) * 100 for d in deviations), default=0.0)
        confidence = 1.0 if not issues else 0.8

        return PrimitiveOutput(
            payload={
                "anomalies": anomalies,
                "summary": {
                    "total_periods": len(actuals),
                    "anomaly_count": len(anomalies),
                    "max_deviation_pct": round(max_dev, 2),
                    "expected_per_period": round(expected_per_period, 2),
                },
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={
                "collection_column": collection_col,
                "balance_column": balance_col,
                "rate_column": rate_col,
                "zscore_threshold": threshold,
            },
        )


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


def _period_label(row: dict[str, Any]) -> str:
    for k in row:
        if any(d in k.lower() for d in ("date", "period", "month")):
            if row[k] is not None:
                return str(row[k])
    return str(list(row.values())[0]) if row else "?"
