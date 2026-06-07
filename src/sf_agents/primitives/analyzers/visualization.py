"""Visualization formatter — transforms analysis outputs into chart-ready structures.

This primitive takes raw analysis payloads (from any analyzer) and reformats them
into standardized visualization descriptors that the UI can render as tables,
bar charts, line charts, pie charts, or dashboard cards.

It does NOT call an LLM — it's a pure deterministic transform.
"""

from __future__ import annotations

from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput


def _infer_chart_type(data: Any) -> str:
    """Heuristically determine the best chart type for a payload."""
    if isinstance(data, dict):
        if "periods" in data and "metrics" in data:
            return "dashboard"
        if "anomalies" in data:
            return "table"
        if "comparisons" in data or "assessments" in data:
            return "table"
        # Check if it's a simple key-value distribution
        if all(isinstance(v, (int, float)) for v in data.values()):
            if len(data) <= 8:
                return "pie"
            return "bar"
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return "table"
        return "bar"
    return "text"


def _build_table(data: list[dict], title: str = "") -> dict:
    """Convert a list of dicts to a table visualization descriptor."""
    if not data:
        return {"type": "table", "title": title, "columns": [], "rows": []}
    columns = list(data[0].keys())
    return {
        "type": "table",
        "title": title,
        "columns": columns,
        "rows": [[row.get(c, "") for c in columns] for row in data],
    }


def _build_bar_chart(
    labels: list[str], datasets: list[dict], title: str = ""
) -> dict:
    """Build a bar chart descriptor."""
    return {
        "type": "bar",
        "title": title,
        "labels": labels,
        "datasets": datasets,
    }


def _build_line_chart(
    labels: list[str], datasets: list[dict], title: str = ""
) -> dict:
    """Build a line chart descriptor."""
    return {
        "type": "line",
        "title": title,
        "labels": labels,
        "datasets": datasets,
    }


def _build_pie_chart(labels: list[str], values: list[float], title: str = "") -> dict:
    """Build a pie chart descriptor."""
    return {
        "type": "pie",
        "title": title,
        "labels": labels,
        "values": values,
    }


def _build_kpi_cards(metrics: dict[str, dict], periods: list[str]) -> list[dict]:
    """Build KPI summary cards showing latest value + change."""
    cards = []
    for metric_name, metric_data in metrics.items():
        values = metric_data.get("values", [])
        changes = metric_data.get("changes_pct", [])
        if not values:
            continue
        latest = values[-1]
        change = changes[-1] if changes else None
        cards.append(
            {
                "type": "kpi_card",
                "metric": metric_name,
                "value": latest,
                "change_pct": change,
                "period": periods[-1] if periods else "",
                "trend": (
                    "up" if change and change > 0
                    else "down" if change and change < 0
                    else "flat"
                ),
            }
        )
    return cards


class VisualizationFormatter(BasePrimitive):
    """Transform analysis outputs into UI-renderable visualization descriptors.

    Input args:
        payload (dict): Raw analysis output payload to visualize.
        viz_type (str, optional): Force a visualization type
            (table, bar, line, pie, dashboard). Auto-detected if omitted.
        title (str, optional): Title for the visualization.
        source_primitive (str, optional): Name of the primitive that produced the payload.

    Payload:
        {
            "visualizations": [
                { "type": "bar|line|pie|table|kpi_card|dashboard", ... }
            ],
            "dashboard": { "cards": [...], "charts": [...], "tables": [...] }
        }
    """

    name = "formatter.visualization"
    version = "0.1.0"
    capability = (
        "Transform analysis results into structured visualization descriptors "
        "for the UI. Produces chart-ready data (bar, line, pie, table, dashboard "
        "KPI cards). Use when the user asks for a dashboard, chart, graph, or "
        "tabular view of results. Pure transform — no LLM needed."
    )
    inputs = {
        "payload": "dict: the analysis output payload to visualize.",
        "viz_type": "str, optional: force chart type (table, bar, line, pie, dashboard).",
        "title": "str, optional: title for the visualization.",
        "source_primitive": "str, optional: which primitive produced the payload.",
    }
    outputs = {
        "payload.visualizations": "list[dict]: visualization descriptors for the UI.",
        "payload.dashboard": "dict: organized dashboard with cards, charts, tables.",
    }

    def __init__(self, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        payload: dict = inp.get("payload", {}) or {}
        viz_type: str = inp.get("viz_type", "") or ""
        title: str = inp.get("title", "") or "Analysis Results"
        source: str = inp.get("source_primitive", "") or ""

        visualizations: list[dict] = []
        dashboard: dict = {"cards": [], "charts": [], "tables": []}
        issues: list[str] = []

        if not payload:
            return PrimitiveOutput(
                payload={"visualizations": [], "dashboard": dashboard},
                citations=[],
                confidence=0.3,
                issues=["Empty payload — nothing to visualize"],
            )

        # Auto-detect or use forced type
        effective_type = viz_type or _infer_chart_type(payload)

        # Handle period_comparison output (dashboard format)
        if "periods" in payload and "metrics" in payload:
            periods = payload["periods"]
            metrics = payload["metrics"]

            # KPI cards
            cards = _build_kpi_cards(metrics, periods)
            dashboard["cards"] = cards
            visualizations.extend(cards)

            # Chart data (use pre-built if available, else build from metrics)
            chart_data = payload.get("chart_data", {})
            if chart_data:
                if "bar" in chart_data:
                    bar = _build_bar_chart(
                        chart_data["bar"]["labels"],
                        chart_data["bar"]["datasets"],
                        title="Portfolio Balance & Count",
                    )
                    dashboard["charts"].append(bar)
                    visualizations.append(bar)
                if "line" in chart_data:
                    line = _build_line_chart(
                        chart_data["line"]["labels"],
                        chart_data["line"]["datasets"],
                        title="Rates & Performance Trends",
                    )
                    dashboard["charts"].append(line)
                    visualizations.append(line)
                if "pie" in chart_data and chart_data["pie"].get("periods"):
                    # Latest period pie chart
                    pie_periods = chart_data["pie"]["periods"]
                    latest_period = periods[-1] if periods else ""
                    if latest_period in pie_periods:
                        dist = pie_periods[latest_period]
                        pie = _build_pie_chart(
                            list(dist.keys()),
                            list(dist.values()),
                            title=f"EPC Distribution ({latest_period})",
                        )
                        dashboard["charts"].append(pie)
                        visualizations.append(pie)

            # Highlights table
            if payload.get("highlights"):
                table = _build_table(payload["highlights"], title="Material Movements")
                dashboard["tables"].append(table)
                visualizations.append(table)

            # Metrics comparison table
            metrics_table_rows = []
            for metric_name, metric_data in metrics.items():
                row = {"metric": metric_name}
                for i, period in enumerate(periods):
                    row[period] = metric_data["values"][i]
                    if i > 0 and metric_data["changes_pct"][i] is not None:
                        row[f"{period}_change"] = f"{metric_data['changes_pct'][i]:+.1f}%"
                metrics_table_rows.append(row)
            if metrics_table_rows:
                table = _build_table(
                    metrics_table_rows, title="Period-over-Period Metrics"
                )
                dashboard["tables"].append(table)
                visualizations.append(table)

        # Handle anomaly output
        elif "anomalies" in payload:
            anomalies = payload["anomalies"]
            if anomalies:
                table = _build_table(anomalies, title=title or "Cashflow Anomalies")
                dashboard["tables"].append(table)
                visualizations.append(table)

            summary = payload.get("summary", {})
            if summary:
                cards = [
                    {
                        "type": "kpi_card",
                        "metric": "Total Periods",
                        "value": summary.get("total_periods", 0),
                        "change_pct": None,
                        "trend": "flat",
                    },
                    {
                        "type": "kpi_card",
                        "metric": "Anomaly Count",
                        "value": summary.get("anomaly_count", 0),
                        "change_pct": None,
                        "trend": "up" if summary.get("anomaly_count", 0) > 0 else "flat",
                    },
                    {
                        "type": "kpi_card",
                        "metric": "Max Deviation %",
                        "value": summary.get("max_deviation_pct", 0),
                        "change_pct": None,
                        "trend": "flat",
                    },
                ]
                dashboard["cards"] = cards
                visualizations.extend(cards)

        # Handle distribution / breakdown dicts
        elif effective_type == "pie" and isinstance(payload, dict):
            labels = [str(k) for k in payload.keys()]
            values = [float(v) for v in payload.values() if isinstance(v, (int, float))]
            if labels and values and len(labels) == len(values):
                pie = _build_pie_chart(labels, values, title=title)
                dashboard["charts"].append(pie)
                visualizations.append(pie)

        # Handle list-of-dicts as table
        elif effective_type == "table" and isinstance(payload, dict):
            # Look for list fields to render as tables
            for key, val in payload.items():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    table = _build_table(val, title=key.replace("_", " ").title())
                    dashboard["tables"].append(table)
                    visualizations.append(table)

        # Fallback: render raw payload as single table/text
        elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
            table = _build_table(payload, title=title)
            dashboard["tables"].append(table)
            visualizations.append(table)

        if not visualizations:
            # Last resort: JSON display
            visualizations.append({"type": "json", "title": title, "data": payload})
            issues.append("Could not determine optimal visualization; raw JSON provided")

        return PrimitiveOutput(
            payload={
                "visualizations": visualizations,
                "dashboard": dashboard,
            },
            citations=[],
            confidence=0.95,
            issues=issues,
        )
