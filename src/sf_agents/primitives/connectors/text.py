"""Text connector — wrap plain text in the standard pages format.

Lets any string value (user-provided excerpt, API response, regulatory text,
or text fetched from an external source) flow into the extraction pipeline
as if it came from a PDF connector.

Useful when:
  - The planner needs to pass a text snippet through extractor.general
  - A regulatory document's text is provided directly rather than as a PDF
  - An upstream step produced a text payload that downstream extractors should read
"""

from __future__ import annotations

from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput


class TextConnector(BasePrimitive):
    """Wrap plain text in the standard pages format for downstream extractors.

    Accepts either a single ``text`` string or a ``texts`` list. Each string
    becomes one page in the output. No LLM required.
    """

    name = "connector.text"
    version = "0.1.0"
    capability = (
        "Wrap plain text strings into the standard pages format used by all extractors. "
        "Use when text content is provided directly rather than as a PDF file — for example, "
        "a user-provided document excerpt, regulatory rule text, or output from an API call. "
        "Accepts 'text' (single string) or 'texts' (list of strings). "
        "Output pages can be passed directly to any extractor as the 'pages' input."
    )
    inputs = {
        "text": "str, optional: a single text block to wrap as one page.",
        "texts": "list[str], optional: multiple text blocks, one per page.",
        "document": "str: label for this text source (used in citations).",
    }
    outputs = {
        "payload.document": "str: echoed document label.",
        "payload.pages": "list[{page:int, text:str}]: one entry per input text block.",
        "payload.page_count": "int: number of pages created.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        document: str = str(inp.get("document", "text_input") or "text_input").strip()
        text: Any = inp.get("text")
        texts: Any = inp.get("texts")

        # Build the list of text blocks
        blocks: list[str] = []
        if isinstance(texts, list):
            blocks = [str(t) for t in texts if t and str(t).strip()]
        elif texts is not None:
            blocks = [str(texts)]

        if isinstance(text, str) and text.strip():
            blocks.insert(0, text)  # single text prepended
        elif text is not None and not isinstance(text, str):
            blocks.insert(0, str(text))

        if not blocks:
            return PrimitiveOutput(
                payload={"document": document, "pages": [], "page_count": 0},
                citations=[],
                confidence=0.0,
                issues=["No text content provided. Supply 'text' or 'texts'."],
            )

        pages = [{"page": i + 1, "text": block} for i, block in enumerate(blocks)]
        citations = [
            Citation(
                source=document,
                location=f"page={i + 1}",
                excerpt=block[:200],
            )
            for i, block in enumerate(blocks)
        ]

        return PrimitiveOutput(
            payload={
                "document": document,
                "pages": pages,
                "page_count": len(pages),
            },
            citations=citations,
            confidence=1.0,
            issues=[],
            metadata={"page_count": len(pages)},
        )
