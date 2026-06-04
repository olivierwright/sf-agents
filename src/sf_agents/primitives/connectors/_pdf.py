"""Shared PDF page extraction used by the PDF-backed connectors.

Kept private (underscore) so it is not mistaken for a registrable primitive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_pages(path: Path) -> list[dict[str, Any]]:
    """Extract page-keyed text chunks from a PDF using pypdf.

    Args:
        path: Path to the PDF file.

    Returns:
        A list of ``{"page": <1-based int>, "text": <str>}`` dicts, one per page.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        RuntimeError: If pypdf is unavailable.
    """
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("pypdf is required to read PDF documents.") from exc

    reader = PdfReader(str(path))
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append({"page": index, "text": text})
    return pages
