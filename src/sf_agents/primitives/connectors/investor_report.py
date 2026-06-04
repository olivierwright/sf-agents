"""Connector for the monthly investor report PDFs."""

from __future__ import annotations

from pathlib import Path

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ._pdf import extract_pages


class InvestorReportConnector(BasePrimitive):
    """Load a monthly investor report PDF into page-keyed text chunks.

    Input args:
        path (str): Path to the investor report PDF.

    Payload:
        ``{"document": <name>, "pages": [{"page", "text"}...], "page_count": int}``
    """

    name = "connector.investor_report"
    version = "0.1.0"
    capability = (
        "Load a monthly investor / servicer report PDF and return page-keyed "
        "text chunks (1-based page numbers). Use this to see how operational "
        "terms such as arrears, delinquency and defaults are reported each period."
    )
    inputs = {
        "path": "str: filesystem path to the investor report PDF (a literal from context.documents.investor_report).",
    }
    outputs = {
        "payload.document": "str: the PDF file name.",
        "payload.pages": "list[{page:int, text:str}]: page-keyed text chunks; feed to extractor.definitions as its 'pages' arg.",
        "payload.page_count": "int: number of pages.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        path = Path(inp.get("path", ""))
        pages = extract_pages(path)
        non_empty = sum(1 for p in pages if p["text"].strip())
        issues: list[str] = []
        if non_empty == 0:
            issues.append(
                "No extractable text found on any page; the PDF may be scanned/image-only."
            )
        confidence = 1.0 if non_empty else 0.2
        first_with_text = next((p for p in pages if p["text"].strip()), None)
        citations = []
        if first_with_text is not None:
            citations.append(
                Citation(
                    source=path.name,
                    location=f"page={first_with_text['page']}",
                    excerpt=first_with_text["text"].strip()[:160],
                )
            )
        return PrimitiveOutput(
            payload={
                "document": path.name,
                "pages": pages,
                "page_count": len(pages),
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={"non_empty_pages": non_empty, "path": str(path)},
        )
