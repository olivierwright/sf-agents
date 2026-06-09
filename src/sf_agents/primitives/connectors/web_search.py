"""Web search connector — fetch public web results via Tavily.

This is the only connector that makes outbound HTTP calls. It wraps Tavily
search results into the standard pages format so any downstream extractor or
analyzer can consume them without modification.

Requires the TAVILY_API_KEY environment variable. If absent, the connector
returns a disabled stub (confidence=0.0, absence_certified=True) rather than
raising, so plans that include it degrade gracefully.
"""

from __future__ import annotations

import os
from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

_DEFAULT_MAX_RESULTS = 5


class WebSearchConnector(BasePrimitive):
    """Search the public web via Tavily and return results as pages.

    Each search result becomes one page in the standard ``{page, text}`` format,
    making the output directly compatible with ``extractor.general`` and
    ``analyzer.general`` without any adaptation.
    """

    name = "connector.web_search"
    version = "0.1.0"
    capability = (
        "Search the public web via Tavily and return a list of relevant results "
        "as page-keyed text chunks (same shape as PDF connectors) so any downstream "
        "extractor or analyzer can consume them. Use when a required data point is "
        "absent from local documents (absence_certified=True upstream), or when the "
        "question explicitly requires current public information not present in the "
        "deal documents. Requires TAVILY_API_KEY to be set; returns a disabled stub "
        "with confidence=0.0 if the key is absent."
    )
    inputs = {
        "query": "str: the search query string.",
        "max_results": "int, optional: maximum results to return (default 5).",
    }
    outputs = {
        "payload.document": "str: label 'web_search:<query>' used as citation source.",
        "payload.pages": "list[{page:int, text:str}]: one page per search result.",
        "payload.page_count": "int: number of results returned.",
        "payload.results": "list[{url, title, content, score}]: raw Tavily results.",
        "payload.absence_certified": "bool: True when no results were found.",
        "payload.query": "str: the query that was executed.",
    }

    def __init__(self, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        self._api_key: str = os.environ.get("TAVILY_API_KEY", "").strip()

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        query: str = str(inp.get("query", "") or "").strip()
        max_results: int = int(inp.get("max_results", _DEFAULT_MAX_RESULTS) or _DEFAULT_MAX_RESULTS)
        document = f"web_search:{query[:60]}"

        if not query:
            return PrimitiveOutput(
                payload={"document": document, "pages": [], "page_count": 0,
                         "results": [], "absence_certified": True, "query": query},
                citations=[],
                confidence=0.0,
                issues=["query is required for connector.web_search"],
            )

        if not self._api_key:
            return PrimitiveOutput(
                payload={"document": document, "pages": [], "page_count": 0,
                         "results": [], "absence_certified": True, "query": query},
                citations=[],
                confidence=0.0,
                issues=["web search disabled: TAVILY_API_KEY not set"],
                metadata={"web_search_enabled": False},
            )

        try:
            from tavily import TavilyClient  # lazy import — tavily-python is optional
            client = TavilyClient(api_key=self._api_key)
            raw = client.search(query, max_results=max_results)
            results: list[dict[str, Any]] = (
                raw.get("results", []) if isinstance(raw, dict) else list(raw)
            )
        except Exception as exc:
            return PrimitiveOutput(
                payload={"document": document, "pages": [], "page_count": 0,
                         "results": [], "absence_certified": True, "query": query},
                citations=[],
                confidence=0.0,
                issues=[f"web search failed: {exc}"],
                metadata={"web_search_enabled": True, "error": str(exc)},
            )

        if not results:
            return PrimitiveOutput(
                payload={"document": document, "pages": [], "page_count": 0,
                         "results": [], "absence_certified": True, "query": query},
                citations=[],
                confidence=0.0,
                issues=[f"no web results found for query: {query!r}"],
                metadata={"web_search_enabled": True},
            )

        pages = [
            {
                "page": i + 1,
                "text": f"[{r.get('title', '')}]\n{r.get('url', '')}\n\n{r.get('content', '')}",
            }
            for i, r in enumerate(results)
        ]
        citations = [
            Citation(
                source=r.get("url", "unknown"),
                location=f"title={r.get('title', '')[:80]}",
                excerpt=r.get("content", "")[:240],
            )
            for r in results
        ]

        scores = [float(r["score"]) for r in results if "score" in r]
        if scores:
            confidence = round(min(max(max(scores), 0.0), 1.0), 4)
        else:
            confidence = round(min(0.5 * len(results) / max_results, 1.0), 4)

        return PrimitiveOutput(
            payload={
                "document": document,
                "pages": pages,
                "page_count": len(pages),
                "results": results,
                "absence_certified": False,
                "query": query,
            },
            citations=citations,
            confidence=confidence,
            issues=[],
            metadata={"web_search_enabled": True, "result_count": len(results)},
        )
