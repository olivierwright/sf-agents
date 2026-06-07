"""Tests for the visualization formatter primitive."""

from sf_agents.primitives.base import PrimitiveInput
from sf_agents.primitives.analyzers.visualization import VisualizationFormatter


def test_viz_dashboard_from_period_comparison():
    formatter = VisualizationFormatter()
    payload = {
        "periods": ["2026-01-31", "2026-02-28"],
        "metrics": {
            "loan_count": {"values": [100, 105], "changes_pct": [None, 5.0]},
            "total_balance": {"values": [20000000, 21000000], "changes_pct": [None, 5.0]},
        },
        "highlights": [
            {"metric": "total_balance", "period": "2026-02-28",
             "direction": "increase", "magnitude_pct": 5.0,
             "from_value": 20000000, "to_value": 21000000,
             "detail": "total_balance increased by 5.0%"},
        ],
        "chart_data": {
            "bar": {"labels": ["2026-01-31", "2026-02-28"],
                    "datasets": [{"label": "Total Balance", "data": [20000000, 21000000]}]},
            "line": {"labels": ["2026-01-31", "2026-02-28"],
                     "datasets": [{"label": "Rate", "data": [3.5, 3.6]}]},
            "pie": {"periods": {"2026-02-28": {"A": 30, "B": 40, "C": 30}}},
        },
    }
    inp = PrimitiveInput(args={"payload": payload, "title": "Test Dashboard"})
    out = formatter.run(inp)
    assert out.confidence >= 0.9
    assert len(out.payload["visualizations"]) > 0
    assert len(out.payload["dashboard"]["cards"]) > 0
    assert len(out.payload["dashboard"]["charts"]) > 0


def test_viz_table_from_anomalies():
    formatter = VisualizationFormatter()
    payload = {
        "anomalies": [
            {"period": "2026-01", "expected": 100, "actual": 150,
             "deviation_pct": 50, "zscore": 3.0},
        ],
        "summary": {"total_periods": 3, "anomaly_count": 1, "max_deviation_pct": 50},
    }
    inp = PrimitiveInput(args={"payload": payload})
    out = formatter.run(inp)
    assert out.confidence >= 0.9
    tables = out.payload["dashboard"]["tables"]
    assert len(tables) == 1
    assert tables[0]["type"] == "table"


def test_viz_empty_payload():
    formatter = VisualizationFormatter()
    inp = PrimitiveInput(args={"payload": {}})
    out = formatter.run(inp)
    assert out.confidence < 0.5
    assert "Empty payload" in out.issues[0]


def test_viz_pie_chart():
    formatter = VisualizationFormatter()
    payload = {"A": 30, "B": 25, "C": 20, "D": 15, "E": 10}
    inp = PrimitiveInput(args={"payload": payload, "title": "Distribution"})
    out = formatter.run(inp)
    assert any(v["type"] == "pie" for v in out.payload["visualizations"])
