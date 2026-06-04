"""Generic connector for any PDF document (SPO, impact report, prospectus, ...).

The Green Lion deal ships several PDFs beyond the prospectus -- the ISS
second-party opinion and the CFP impact report among them. Rather than overload
the prospectus-specific connector, this thin generic connector loads *any* PDF by
path into the same page-keyed shape, so the planner can read each document with a
single, clearly-named capability.
"""

from __future__ import annotations

from pathlib import Path

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ._pdf import extract_pages


class PdfDocumentConnector(BasePrimitive):
    """Load any PDF into page-keyed text chunks (1-based page numbers).

    Input args:
        path (str): Path to the PDF file.

    Payload:
        ``{"document": <name>, "pages": [{"page", "text"}...], "page_count": int}``
    """

    name = "connector.pdf_document"
    version = "0.1.0"
    capability = (
        "Load any PDF document (second-party opinion, impact report, prospectus, "
        "investor report, ...) into page-keyed text chunks with 1-based page "
        "numbers. Use one load step per PDF you need to read; the page numbers it "
        "returns are what downstream citations point at."
    )
    inputs = {
        "path": "str: filesystem path to the PDF (a literal from context.documents.<name>).",
    }
    outputs = {
        "payload.document": "str: the PDF file name (use as a citation source).",
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
