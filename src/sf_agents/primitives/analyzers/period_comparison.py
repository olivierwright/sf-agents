"""Month-over-month (period-over-period) loan tape comparison.

Compares key portfolio metrics across multiple reporting periods to highlight
changes, trends, and material movements. Works with the Green Lion monthly
tape files or any set of ESMA-style loan tapes sharing the same schema.

Produces a structured payload suitable for dashboard rendering (tables, charts).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a structured-finance portfolio analyst. Given period-over-period "
    "portfolio metrics, provide a concise narrative summary of the key movements "
    "and any material changes that warrant attention. Focus on trends, not individual "
    "numbers. Be specific about direction and magnitude."
)


def _safe_pct_change(old: float, new: float) -> float | None:
    """Percentage change from old to new; None if old is zero."""
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 2)


def _bucket_distribution(rows: list[dict], column: str) -> dict[str, int]:
    """Count occurrences of each value in a column."""
    dist: dict[str, int] = {}
    for row in rows:
        val = str(row.get(column, "unknown"))
        dist[val] = dist.get(val, 0) + 1
    return dict(sorted(dist.items()))


class PeriodComparisonAnalyzer(BasePrimitive):
    """Compare loan tape metrics across multiple reporting periods.

    Input args:
        periods (list[dict]): Each dict has:
            - document (str): file name / source identifier
            - reporting_date (str): period label (e.g. "2026-01-31")
            - columns (list[str]): column names
            - rows (list[dict]): row data
        metrics (list[str], optional): Specific metrics to compare.
            Defaults to a standard set of portfolio KPIs.

    Payload:
        {
            "periods": ["2026-01", "2026-02", "2026-03"],
            "metrics": { "<metric_name>": { "values": [...], "changes_pct": [...] } },
            "distributions": { "<column>": { "<period>": { "<bucket>": count } } },
            "highlights": [{ "metric", "direction", "magnitude_pct", "detail" }],
            "narrative": "<LLM-generated summary>"
        }
    """

    name = "analyzer.period_comparison"
    version = "0.1.0"
    capability = (
        "Compare loan tape portfolio metrics across multiple reporting periods "
        "(month-over-month). Computes changes in balance, count, interest rates, "
        "arrears, EPC distribution, and other KPIs. Returns structured data suitable "
        "for table and chart rendering, plus highlights of material movements. "
        "Requires multiple connector.loan_tape outputs from different periods."
    )
    inputs = {
        "periods": (
            "list[dict]: each with keys 'document', 'reporting_date', 'columns', 'rows'. "
            "Typically from multiple connector.loan_tape calls on different monthly files."
        ),
        "metrics": "list[str], optional: specific metrics to compare (default: standard KPIs).",
    }
    outputs = {
        "payload.periods": "list[str]: ordered period labels.",
        "payload.metrics": (
            "dict: keyed by metric name, each with 'values' (per period) and 'changes_pct'."
        ),
        "payload.distributions": (
            "dict: keyed by category column, each period maps buckets to counts."
        ),
        "payload.highlights": (
            "list[dict]: material movements with metric, direction, magnitude_pct, detail."
        ),
        "payload.narrative": "str: LLM-generated narrative summary of key trends.",
        "payload.chart_data": (
            "dict: pre-formatted data for common chart types (bar, line, pie)."
        ),
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        periods_data: list[dict] = inp.get("periods", []) or []
        requested_metrics: list[str] = inp.get("metrics", []) or []

        if len(periods_data) < 2:
            return PrimitiveOutput(
                payload={"error": "At least 2 periods required for comparison"},
                citations=[],
                confidence=0.0,
                issues=["Need at least 2 periods for month-over-month comparison"],
            )

        # Sort periods by reporting_date
        periods_data.sort(key=lambda p: p.get("reporting_date", ""))

        period_labels: list[str] = []
        period_stats: list[dict[str, Any]] = []
        citations: list[Citation] = []
        issues: list[str] = []

        # Standard metrics to compute
        standard_metrics = [
            "loan_count",
            "total_balance",
            "avg_balance",
            "avg_interest_rate_pct",
            "weighted_avg_rate",
            "performing_pct",
            "arrears_pct",
            "green_label_pct",
            "avg_ltv",
        ]
        metrics_to_use = requested_metrics if requested_metrics else standard_metrics

        # Distribution columns to track
        dist_columns = ["epc_label", "performing_status", "arrears_bucket", "rate_type"]

        for period in periods_data:
            doc = period.get("document", "unknown")
            reporting_date = period.get("reporting_date", "unknown")
            rows = period.get("rows", [])
            columns = period.get("columns", [])

            period_labels.append(reporting_date)

            # Compute KPIs for this period
            stats: dict[str, Any] = {}
            stats["loan_count"] = len(rows)

            # Balance metrics
            balances = [
                float(r["current_balance"])
                for r in rows
                if r.get("current_balance") is not None
            ]
            stats["total_balance"] = round(sum(balances), 2) if balances else 0
            stats["avg_balance"] = (
                round(sum(balances) / len(balances), 2) if balances else 0
            )

            # Interest rate metrics
            rates = [
                float(r["current_interest_rate_pct"])
                for r in rows
                if r.get("current_interest_rate_pct") is not None
            ]
            stats["avg_interest_rate_pct"] = (
                round(sum(rates) / len(rates), 4) if rates else 0
            )

            # Weighted average rate (by balance)
            if balances and rates and len(balances) == len(rows):
                weighted_sum = sum(
                    float(r.get("current_balance", 0))
                    * float(r.get("current_interest_rate_pct", 0))
                    for r in rows
                    if r.get("current_balance") is not None
                    and r.get("current_interest_rate_pct") is not None
                )
                total_bal = sum(balances)
                stats["weighted_avg_rate"] = (
                    round(weighted_sum / total_bal, 4) if total_bal > 0 else 0
                )
            else:
                stats["weighted_avg_rate"] = stats["avg_interest_rate_pct"]

            # Performance metrics
            performing_count = sum(
                1 for r in rows if r.get("performing_status") == "Non-defaulted"
            )
            stats["performing_pct"] = (
                round(performing_count / len(rows) * 100, 2) if rows else 0
            )

            arrears_count = sum(
                1 for r in rows if r.get("arrears_bucket", "Performing") != "Performing"
            )
            stats["arrears_pct"] = (
                round(arrears_count / len(rows) * 100, 2) if rows else 0
            )

            # Green metrics
            green_labels = {"A", "A+", "A++", "A+++", "B"}
            green_count = sum(
                1 for r in rows if r.get("epc_label") in green_labels
            )
            stats["green_label_pct"] = (
                round(green_count / len(rows) * 100, 2) if rows else 0
            )

            # LTV
            ltvs = [
                float(r["cltomv_current"])
                for r in rows
                if r.get("cltomv_current") is not None
            ]
            stats["avg_ltv"] = round(sum(ltvs) / len(ltvs), 2) if ltvs else 0

            period_stats.append(stats)

            # Citation for this period
            citations.append(
                Citation(
                    source=doc,
                    location=f"reporting_date={reporting_date}",
                    excerpt=f"Period {reporting_date}: {len(rows)} loans, balance={stats['total_balance']:.0f}",
                )
            )

        # Build metrics payload with period-over-period changes
        metrics_payload: dict[str, dict] = {}
        for metric in metrics_to_use:
            values = [s.get(metric, 0) for s in period_stats]
            changes: list[float | None] = [None]  # first period has no prior
            for i in range(1, len(values)):
                changes.append(_safe_pct_change(values[i - 1], values[i]))
            metrics_payload[metric] = {"values": values, "changes_pct": changes}

        # Build distribution data for charts
        distributions: dict[str, dict[str, dict[str, int]]] = {}
        for col in dist_columns:
            # Check if column exists in data
            if periods_data[0].get("rows") and col in (
                periods_data[0].get("columns", [])
            ):
                distributions[col] = {}
                for i, period in enumerate(periods_data):
                    distributions[col][period_labels[i]] = _bucket_distribution(
                        period.get("rows", []), col
                    )

        # Identify highlights (material movements > 5% change)
        highlights: list[dict] = []
        for metric, data in metrics_payload.items():
            for i, change in enumerate(data["changes_pct"]):
                if change is not None and abs(change) > 5.0:
                    direction = "increase" if change > 0 else "decrease"
                    highlights.append(
                        {
                            "metric": metric,
                            "period": period_labels[i],
                            "direction": direction,
                            "magnitude_pct": abs(change),
                            "from_value": data["values"][i - 1],
                            "to_value": data["values"][i],
                            "detail": (
                                f"{metric} {direction}d by {abs(change):.1f}% "
                                f"from {period_labels[i-1]} to {period_labels[i]}"
                            ),
                        }
                    )

        # Sort highlights by magnitude
        highlights.sort(key=lambda h: h["magnitude_pct"], reverse=True)

        # Build chart-ready data structures
        chart_data = {
            "bar": {
                "labels": period_labels,
                "datasets": [
                    {
                        "label": "Total Balance (EUR)",
                        "data": metrics_payload.get("total_balance", {}).get("values", []),
                    },
                    {
                        "label": "Loan Count",
                        "data": metrics_payload.get("loan_count", {}).get("values", []),
                    },
                ],
            },
            "line": {
                "labels": period_labels,
                "datasets": [
                    {
                        "label": "Avg Interest Rate (%)",
                        "data": metrics_payload.get("avg_interest_rate_pct", {}).get(
                            "values", []
                        ),
                    },
                    {
                        "label": "Performing (%)",
                        "data": metrics_payload.get("performing_pct", {}).get(
                            "values", []
                        ),
                    },
                    {
                        "label": "Green Label (%)",
                        "data": metrics_payload.get("green_label_pct", {}).get(
                            "values", []
                        ),
                    },
                ],
            },
            "pie": {
                "periods": {},
            },
        }
        # Pie chart data per period for EPC distribution
        if "epc_label" in distributions:
            chart_data["pie"]["periods"] = distributions["epc_label"]

        # Generate narrative with LLM
        narrative = ""
        try:
            narrative_prompt = (
                f"Periods: {period_labels}\n\n"
                f"Key metrics:\n"
            )
            for metric, data in metrics_payload.items():
                narrative_prompt += f"  {metric}: {data['values']} (changes: {data['changes_pct']})\n"
            if highlights:
                narrative_prompt += f"\nMaterial movements (>5% change):\n"
                for h in highlights[:5]:
                    narrative_prompt += f"  - {h['detail']}\n"

            resp = self._llm(
                system=_SYSTEM,
                prompt=narrative_prompt,
                schema={
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "2-4 sentence narrative of key trends and movements",
                        },
                    },
                    "required": ["summary"],
                },
            )
            narrative = resp.get("summary", "") if isinstance(resp, dict) else ""
        except Exception:
            narrative = (
                f"Portfolio tracked across {len(period_labels)} periods. "
                f"{len(highlights)} material movements detected."
            )
            if highlights:
                narrative += f" Largest: {highlights[0]['detail']}."

        confidence = 0.92 if len(periods_data) >= 2 else 0.5

        return PrimitiveOutput(
            payload={
                "periods": period_labels,
                "metrics": metrics_payload,
                "distributions": distributions,
                "highlights": highlights,
                "narrative": narrative,
                "chart_data": chart_data,
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
        )
