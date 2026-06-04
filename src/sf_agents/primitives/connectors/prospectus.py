"""Connector for the offering circular / prospectus PDF."""

from __future__ import annotations

from pathlib import Path

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ._pdf import extract_pages


class ProspectusConnector(BasePrimitive):
    """Load a prospectus PDF into page-keyed text chunks.

    Input args:
        path (str): Path to the prospectus PDF.

    Payload:
        ``{"document": <name>, "pages": [{"page", "text"}...], "page_count": int}``
    """

    name = "connector.prospectus"
    version = "0.1.0"
    capability = (
        "Load an offering circular / prospectus PDF and return page-keyed text "
        "chunks (1-based page numbers). Use this to obtain the source pages that "
        "formal defined terms (e.g. Arrears, Default, Cure) are extracted from."
    )
    inputs = {
        "path": "str: filesystem path to the prospectus PDF (a literal from context.documents.prospectus).",
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
            excerpt = first_with_text["text"].strip()[:160]
            citations.append(
                Citation(
                    source=path.name,
                    location=f"page={first_with_text['page']}",
                    excerpt=excerpt,
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
