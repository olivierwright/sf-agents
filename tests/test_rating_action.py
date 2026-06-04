"""Tests for analyzer.rating_action."""

from __future__ import annotations

from sf_agents.primitives.analyzers.rating_action import RatingActionAnalyzer
from sf_agents.primitives.base import PrimitiveInput


def _pages(text_by_page: dict[int, str]) -> list[dict]:
    return [{"page": p, "text": t} for p, t in text_by_page.items()]


def _tape() -> tuple[list[str], list[dict]]:
    cols = ["loan_id", "arrears_bucket", "default_crr_flag", "current_balance"]
    rows = [{"loan_id": str(i), "arrears_bucket": "0", "default_crr_flag": "N",
             "current_balance": 200_000.0}
            for i in range(50)]
    return cols, rows


def test_parses_affirm_action(mock_llm):
    pages = _pages({2: "Class A notes affirmed at AAA by Fitch Ratings."})
    cols, rows = _tape()
    analyzer = RatingActionAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "pages": pages,
        "document": "rating_action.pdf",
        "tape_columns": cols,
        "tape_rows": rows,
        "tape_document": "loan_tape.csv",
    }))

    actions = out.payload["rating_actions"]
    assert len(actions) >= 1
    assert actions[0]["action_type"] == "affirm"
    assert actions[0]["new_rating"] == "AAA"


def test_tape_metrics_computed(mock_llm):
    pages = _pages({2: "Class A notes affirmed at AAA."})
    cols, rows = _tape()
    analyzer = RatingActionAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "pages": pages,
        "document": "rating_action.pdf",
        "tape_columns": cols,
        "tape_rows": rows,
        "tape_document": "loan_tape.csv",
    }))

    assert "arrears_rate_pct" in out.metadata["tape_metrics"]
    assert out.metadata["tape_metrics"]["arrears_rate_pct"] == 0.0


def test_tape_citation_present(mock_llm):
    pages = _pages({2: "Class A notes affirmed at AAA."})
    cols, rows = _tape()
    analyzer = RatingActionAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "pages": pages,
        "document": "rating_action.pdf",
        "tape_columns": cols,
        "tape_rows": rows,
        "tape_document": "loan_tape.csv",
    }))

    tape_cites = [c for c in out.citations if c.source == "loan_tape.csv"]
    assert len(tape_cites) >= 1


def test_no_pages_returns_empty(mock_llm):
    cols, rows = _tape()
    analyzer = RatingActionAnalyzer(llm=mock_llm)
    out = analyzer(PrimitiveInput(args={
        "pages": [],
        "document": "rating_action.pdf",
        "tape_columns": cols,
        "tape_rows": rows,
        "tape_document": "loan_tape.csv",
    }))

    assert out.payload["rating_actions"] == []
    assert out.confidence == 0.0
