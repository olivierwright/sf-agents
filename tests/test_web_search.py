"""Offline tests for connector.web_search (WebSearchConnector).

All tests use sys.modules monkeypatching to avoid a real Tavily network call.
"""
from __future__ import annotations

import sys
import types

import pytest

from sf_agents.orchestrator.registry import build_default_registry
from sf_agents.primitives.base import PrimitiveInput
from sf_agents.primitives.connectors.web_search import WebSearchConnector

_FAKE_RESULTS = [
    {
        "url": "https://example.com/euribor",
        "title": "EURIBOR 3M Current Rate",
        "content": "The current EURIBOR 3-month rate is 3.45% as of June 2026.",
        "score": 0.92,
    },
    {
        "url": "https://example.com/ecb",
        "title": "ECB Rate Decisions",
        "content": "The European Central Bank maintained rates at their June 2026 meeting.",
        "score": 0.78,
    },
]


def _patch_tavily(monkeypatch, results):
    fake_mod = types.ModuleType("tavily")

    class FakeClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results=5):
            return {"results": results}

    fake_mod.TavilyClient = FakeClient
    monkeypatch.setitem(sys.modules, "tavily", fake_mod)


def _make_connector(monkeypatch, api_key="test-key"):
    monkeypatch.setenv("TAVILY_API_KEY", api_key)
    return WebSearchConnector()


# ---------------------------------------------------------------------------
# Stub path: no key
# ---------------------------------------------------------------------------

def test_no_key_returns_stub(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    connector = WebSearchConnector()
    out = connector(PrimitiveInput(args={"query": "EURIBOR 3M rate"}))

    assert out.confidence == 0.0
    assert out.payload["absence_certified"] is True
    assert any("TAVILY_API_KEY not set" in issue for issue in out.issues)
    assert out.payload["page_count"] == 0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_with_key_returns_pages(monkeypatch):
    _patch_tavily(monkeypatch, _FAKE_RESULTS)
    connector = _make_connector(monkeypatch)
    out = connector(PrimitiveInput(args={"query": "EURIBOR 3M rate"}))

    assert out.payload["page_count"] == 2
    assert len(out.citations) == 2
    assert out.citations[0].source == "https://example.com/euribor"
    assert out.citations[0].location.startswith("title=")
    assert out.confidence > 0.0
    assert out.payload["absence_certified"] is False
    assert out.payload["query"] == "EURIBOR 3M rate"


# ---------------------------------------------------------------------------
# No-results path
# ---------------------------------------------------------------------------

def test_no_results_certifies_absence(monkeypatch):
    _patch_tavily(monkeypatch, [])
    connector = _make_connector(monkeypatch)
    out = connector(PrimitiveInput(args={"query": "obscure missing data point"}))

    assert out.payload["absence_certified"] is True
    assert out.confidence == 0.0
    assert out.payload["page_count"] == 0


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------

def test_tavily_error_returns_issues(monkeypatch):
    fake_mod = types.ModuleType("tavily")

    class ErrorClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results=5):
            raise RuntimeError("network error")

    fake_mod.TavilyClient = ErrorClient
    monkeypatch.setitem(sys.modules, "tavily", fake_mod)
    connector = _make_connector(monkeypatch)
    out = connector(PrimitiveInput(args={"query": "any query"}))

    assert any("web search failed" in issue for issue in out.issues)
    assert out.confidence == 0.0
    assert out.payload["absence_certified"] is True


# ---------------------------------------------------------------------------
# Empty query
# ---------------------------------------------------------------------------

def test_empty_query_returns_issues(monkeypatch):
    _patch_tavily(monkeypatch, _FAKE_RESULTS)
    connector = _make_connector(monkeypatch)
    out = connector(PrimitiveInput(args={"query": ""}))

    assert any("query is required" in issue for issue in out.issues)
    assert out.confidence == 0.0


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

def test_registered_in_default_registry():
    registry = build_default_registry()
    assert "connector.web_search" in registry.names()


# ---------------------------------------------------------------------------
# Downstream compatibility — pages shape
# ---------------------------------------------------------------------------

def test_pages_are_downstream_compatible(monkeypatch):
    _patch_tavily(monkeypatch, _FAKE_RESULTS)
    connector = _make_connector(monkeypatch)
    out = connector(PrimitiveInput(args={"query": "test"}))

    for page in out.payload["pages"]:
        assert isinstance(page["page"], int)
        assert isinstance(page["text"], str) and page["text"].strip()
