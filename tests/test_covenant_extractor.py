"""Tests for extractor.covenants."""

from __future__ import annotations

from sf_agents.primitives.base import PrimitiveInput
from sf_agents.primitives.extractors.covenants import CovenantExtractor


def _pages(text_by_page: dict[int, str]) -> list[dict]:
    return [{"page": p, "text": t} for p, t in text_by_page.items()]


def test_extracts_covenants(mock_llm):
    pages = _pages({
        8: "OC Ratio Test: must be at least 105% of the note balance.",
        9: "PDL Trigger: arrears exceed 2% of collateral balance.",
    })
    ext = CovenantExtractor(llm=mock_llm)
    out = ext(PrimitiveInput(args={"pages": pages, "document": "prospectus.pdf"}))

    assert out.payload["document"] == "prospectus.pdf"
    covenants = out.payload["covenants"]
    assert len(covenants) >= 1
    types = [c["type"] for c in covenants]
    assert any("OC" in t or "ratio" in t.lower() for t in types)


def test_citations_reference_real_pages(mock_llm):
    pages = _pages({
        8: "OC Ratio Test must be at least 105%. PDL Trigger: arrears exceed 2%.",
    })
    ext = CovenantExtractor(llm=mock_llm)
    out = ext(PrimitiveInput(args={"pages": pages, "document": "prospectus.pdf"}))

    cited = {c.location for c in out.citations}
    assert "page=8" in cited


def test_covenant_type_filter(mock_llm):
    pages = _pages({8: "OC Ratio Test 105%. PDL Trigger 2%."})
    ext = CovenantExtractor(llm=mock_llm)
    out = ext(PrimitiveInput(args={
        "pages": pages,
        "document": "prospectus.pdf",
        "covenant_types": ["OC ratio"],
    }))
    # Only OC ratio covenants should survive the filter
    covenants = out.payload["covenants"]
    for cov in covenants:
        assert "oc" in cov["type"].lower() or "ratio" in cov["type"].lower()


def test_no_pages_returns_empty(mock_llm):
    ext = CovenantExtractor(llm=mock_llm)
    out = ext(PrimitiveInput(args={"pages": [], "document": "prospectus.pdf"}))
    assert out.payload["covenants"] == []
    assert out.confidence == 0.0
