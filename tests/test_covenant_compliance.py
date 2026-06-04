"""Tests for analyzer.covenant_compliance — fully deterministic."""

from __future__ import annotations

from sf_agents.primitives.analyzers.covenant_compliance import CovenantComplianceAnalyzer
from sf_agents.primitives.base import PrimitiveInput


def _make_tape(arrears_rate: float = 0.01, n: int = 100) -> tuple[list[str], list[dict]]:
    """Build a minimal loan tape where arrears_rate fraction of loans are delinquent."""
    n_arrears = int(n * arrears_rate)
    cols = ["loan_id", "arrears_bucket", "current_balance"]
    rows = []
    for i in range(n):
        rows.append({
            "loan_id": str(i),
            "arrears_bucket": "1" if i < n_arrears else "0",
            "current_balance": 200_000.0,
        })
    return cols, rows


def test_pdl_trigger_passes_when_below_threshold():
    cols, rows = _make_tape(arrears_rate=0.01)  # 1% arrears
    covenants = [{"type": "PDL trigger", "threshold": "2%", "page": 9,
                  "excerpt": "PDL Trigger: 2%"}]
    analyzer = CovenantComplianceAnalyzer()
    out = analyzer(PrimitiveInput(args={
        "covenants": covenants,
        "covenant_document": "prospectus.pdf",
        "tape_columns": cols,
        "tape_rows": rows,
        "tape_document": "loan_tape.csv",
    }))

    results = out.payload["covenant_results"]
    assert len(results) == 1
    assert results[0]["status"] == "pass"
    assert out.payload["overall_ok"] is True


def test_pdl_trigger_fails_when_above_threshold():
    cols, rows = _make_tape(arrears_rate=0.05)  # 5% arrears
    covenants = [{"type": "PDL trigger", "threshold": "2%", "page": 9,
                  "excerpt": "PDL Trigger: 2%"}]
    analyzer = CovenantComplianceAnalyzer()
    out = analyzer(PrimitiveInput(args={
        "covenants": covenants,
        "covenant_document": "prospectus.pdf",
        "tape_columns": cols,
        "tape_rows": rows,
        "tape_document": "loan_tape.csv",
    }))

    results = out.payload["covenant_results"]
    assert results[0]["status"] == "fail"
    assert out.payload["overall_ok"] is False


def test_not_verifiable_when_column_missing():
    covenants = [{"type": "PDL trigger", "threshold": "2%", "page": 9, "excerpt": ""}]
    analyzer = CovenantComplianceAnalyzer()
    out = analyzer(PrimitiveInput(args={
        "covenants": covenants,
        "covenant_document": "prospectus.pdf",
        "tape_columns": ["loan_id"],  # no arrears column
        "tape_rows": [{"loan_id": "1"}],
        "tape_document": "loan_tape.csv",
    }))

    assert out.payload["covenant_results"][0]["status"] == "not_verifiable"


def test_covenant_citation_includes_prospectus_page():
    cols, rows = _make_tape()
    covenants = [{"type": "PDL trigger", "threshold": "2%", "page": 9, "excerpt": "PDL 2%"}]
    analyzer = CovenantComplianceAnalyzer()
    out = analyzer(PrimitiveInput(args={
        "covenants": covenants,
        "covenant_document": "prospectus.pdf",
        "tape_columns": cols,
        "tape_rows": rows,
        "tape_document": "loan_tape.csv",
    }))

    sources = {c.source for c in out.citations}
    assert "prospectus.pdf" in sources
