"""Tests for the period comparison analyzer."""

import pytest
from sf_agents.primitives.base import PrimitiveInput
from sf_agents.primitives.analyzers.period_comparison import PeriodComparisonAnalyzer


def _mock_llm(**kwargs):
    return {"summary": "Test narrative: portfolio stable across periods."}


def _make_rows(count, balance_base, rate, arrears_pct=0):
    """Generate synthetic loan rows."""
    rows = []
    for i in range(count):
        is_arrears = i < int(count * arrears_pct / 100)
        rows.append({
            "loan_id": f"GL_{i:04d}",
            "current_balance": balance_base + i * 100,
            "current_interest_rate_pct": rate,
            "performing_status": "Non-defaulted",
            "arrears_bucket": "1-30 days" if is_arrears else "Performing",
            "epc_label": "A" if i % 3 == 0 else ("B" if i % 3 == 1 else "C"),
            "cltomv_current": 80.0 + i * 0.1,
            "rate_type": "Fixed",
        })
    return rows


def test_period_comparison_basic():
    analyzer = PeriodComparisonAnalyzer(llm=_mock_llm)
    inp = PrimitiveInput(args={
        "periods": [
            {
                "document": "tape_jan.csv",
                "reporting_date": "2026-01-31",
                "columns": ["loan_id", "current_balance", "current_interest_rate_pct",
                             "performing_status", "arrears_bucket", "epc_label",
                             "cltomv_current", "rate_type"],
                "rows": _make_rows(100, 200000, 3.5),
            },
            {
                "document": "tape_feb.csv",
                "reporting_date": "2026-02-28",
                "columns": ["loan_id", "current_balance", "current_interest_rate_pct",
                             "performing_status", "arrears_bucket", "epc_label",
                             "cltomv_current", "rate_type"],
                "rows": _make_rows(100, 210000, 3.6),
            },
        ],
    })
    out = analyzer.run(inp)
    assert out.confidence > 0.5
    assert "periods" in out.payload
    assert len(out.payload["periods"]) == 2
    assert "metrics" in out.payload
    assert "loan_count" in out.payload["metrics"]
    assert "chart_data" in out.payload
    assert len(out.citations) == 2


def test_period_comparison_detects_changes():
    analyzer = PeriodComparisonAnalyzer(llm=_mock_llm)
    inp = PrimitiveInput(args={
        "periods": [
            {
                "document": "tape_jan.csv",
                "reporting_date": "2026-01-31",
                "columns": ["loan_id", "current_balance", "current_interest_rate_pct",
                             "performing_status", "arrears_bucket", "epc_label",
                             "cltomv_current", "rate_type"],
                "rows": _make_rows(100, 200000, 3.5),
            },
            {
                "document": "tape_feb.csv",
                "reporting_date": "2026-02-28",
                "columns": ["loan_id", "current_balance", "current_interest_rate_pct",
                             "performing_status", "arrears_bucket", "epc_label",
                             "cltomv_current", "rate_type"],
                # Significantly higher balances → should trigger highlight
                "rows": _make_rows(100, 300000, 3.6),
            },
        ],
    })
    out = analyzer.run(inp)
    assert len(out.payload["highlights"]) > 0
    # Total balance should show >5% change
    balance_highlight = [h for h in out.payload["highlights"] if h["metric"] == "total_balance"]
    assert len(balance_highlight) > 0
    assert balance_highlight[0]["direction"] == "increase"


def test_period_comparison_three_periods():
    analyzer = PeriodComparisonAnalyzer(llm=_mock_llm)
    inp = PrimitiveInput(args={
        "periods": [
            {
                "document": "tape_jan.csv",
                "reporting_date": "2026-01-31",
                "columns": ["loan_id", "current_balance", "current_interest_rate_pct",
                             "performing_status", "arrears_bucket", "epc_label",
                             "cltomv_current", "rate_type"],
                "rows": _make_rows(100, 200000, 3.5),
            },
            {
                "document": "tape_feb.csv",
                "reporting_date": "2026-02-28",
                "columns": ["loan_id", "current_balance", "current_interest_rate_pct",
                             "performing_status", "arrears_bucket", "epc_label",
                             "cltomv_current", "rate_type"],
                "rows": _make_rows(100, 205000, 3.6),
            },
            {
                "document": "tape_mar.csv",
                "reporting_date": "2026-03-31",
                "columns": ["loan_id", "current_balance", "current_interest_rate_pct",
                             "performing_status", "arrears_bucket", "epc_label",
                             "cltomv_current", "rate_type"],
                "rows": _make_rows(100, 210000, 3.7),
            },
        ],
    })
    out = analyzer.run(inp)
    assert len(out.payload["periods"]) == 3
    # Each metric should have 3 values and 3 changes (first is None)
    for metric_data in out.payload["metrics"].values():
        assert len(metric_data["values"]) == 3
        assert metric_data["changes_pct"][0] is None


def test_period_comparison_insufficient_periods():
    analyzer = PeriodComparisonAnalyzer(llm=_mock_llm)
    inp = PrimitiveInput(args={
        "periods": [
            {
                "document": "tape_jan.csv",
                "reporting_date": "2026-01-31",
                "columns": [],
                "rows": [],
            },
        ],
    })
    out = analyzer.run(inp)
    assert out.confidence == 0.0
    assert "error" in out.payload
