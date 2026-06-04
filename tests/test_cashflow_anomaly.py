"""Tests for analyzer.cashflow_anomaly — mostly deterministic."""

from __future__ import annotations

from sf_agents.primitives.analyzers.cashflow_anomaly import CashflowAnomalyAnalyzer
from sf_agents.primitives.base import PrimitiveInput


def _tape_rows(n: int = 100, balance: float = 200_000.0, rate: float = 3.5) -> list[dict]:
    return [{"loan_id": str(i), "current_balance": balance, "current_interest_rate_pct": rate}
            for i in range(n)]


def _remittance_rows(actuals: list[float]) -> list[dict]:
    return [{"period": f"2026-{i+1:02d}", "period_collections": v} for i, v in enumerate(actuals)]


def _remittance_cols() -> list[str]:
    return ["period", "period_collections"]


def _tape_cols() -> list[str]:
    return ["loan_id", "current_balance", "current_interest_rate_pct"]


def test_flags_obvious_outlier(mock_llm):
    # 100 loans, balance=200k, rate=3.5% → expected ≈ 583.33 each → total ≈ 58333/period
    tape = _tape_rows()
    expected = sum(200_000 * 3.5 / 100 / 12 for _ in range(100))  # ~58333

    # 11 periods: 10 normal, 1 huge outlier (3×)
    actuals = [expected] * 10 + [expected * 3.0]
    rem_rows = _remittance_rows(actuals)

    analyzer = CashflowAnomalyAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "remittance_columns": _remittance_cols(),
        "remittance_rows": rem_rows,
        "remittance_document": "remittance.csv",
        "tape_columns": _tape_cols(),
        "tape_rows": tape,
        "tape_document": "loan_tape.csv",
    }))

    anomalies = out.payload["anomalies"]
    assert len(anomalies) >= 1
    assert anomalies[-1]["remittance_row"] == 10  # last period is the outlier


def test_no_anomalies_when_all_normal(mock_llm):
    tape = _tape_rows()
    expected = sum(200_000 * 3.5 / 100 / 12 for _ in range(100))
    actuals = [expected * (1 + i * 0.001) for i in range(8)]  # tiny variations

    analyzer = CashflowAnomalyAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "remittance_columns": _remittance_cols(),
        "remittance_rows": _remittance_rows(actuals),
        "remittance_document": "remittance.csv",
        "tape_columns": _tape_cols(),
        "tape_rows": tape,
        "tape_document": "loan_tape.csv",
    }))

    assert out.payload["summary"]["anomaly_count"] == 0


def test_returns_tape_citation(mock_llm):
    tape = _tape_rows()
    actuals = [50000.0] * 5
    analyzer = CashflowAnomalyAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "remittance_columns": _remittance_cols(),
        "remittance_rows": _remittance_rows(actuals),
        "remittance_document": "remittance.csv",
        "tape_columns": _tape_cols(),
        "tape_rows": tape,
        "tape_document": "loan_tape.csv",
    }))

    tape_citations = [c for c in out.citations if c.source == "loan_tape.csv"]
    assert len(tape_citations) >= 1


def test_missing_collection_column_returns_zero_confidence(mock_llm):
    analyzer = CashflowAnomalyAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "remittance_columns": ["period", "unknown_col"],
        "remittance_rows": [{"period": "2026-01", "unknown_col": 1000.0}],
        "remittance_document": "remittance.csv",
        "tape_columns": _tape_cols(),
        "tape_rows": _tape_rows(),
        "tape_document": "loan_tape.csv",
    }))

    assert out.confidence == 0.0
    assert out.payload["anomalies"] == []
