"""Auto-detecting file connector.

Loads any supported file format without the caller needing to know which
specific connector to use. Detects by file extension first, then by content
sniffing. Returns the same payload shapes as the domain-specific connectors
so downstream primitives are interchangeable.

Supported formats
-----------------
Tabular  : CSV, TSV, XLSX, XLS, JSON (array of objects), JSONL
Text/PDF : PDF, TXT, MD
Semi-str : JSON object → wrapped as one-page text

Auto-detection order (tabular files)
-------------------------------------
1. Extension: .csv/.tsv/.xlsx/.xls/.json/.jsonl → tabular path
2. Content: sniff delimiter (comma, semicolon, tab, pipe)
3. Encoding: UTF-8 → UTF-8-BOM → Latin-1 fallback chain
4. Header: row-0 is header if it contains more non-numeric tokens than row-1
"""

from __future__ import annotations

import io
import json
import pathlib
from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

# Maximum rows to return in full (the full tape can be very large)
_MAX_ROWS = 10_000
# Rows kept as a quick sample for schema inference
_SAMPLE_ROWS = 20
# Minimum string tokens in a row for it to be considered a header
_HEADER_STRING_RATIO = 0.5


class AutoConnector(BasePrimitive):
    """Load any supported file format, auto-detecting format and encoding.

    Returns the same payload shape as domain-specific connectors so all
    downstream extractors and analyzers accept its output directly.
    """

    name = "connector.auto"
    version = "0.1.0"
    capability = (
        "Load any supported file (CSV, TSV, XLSX, XLS, JSON, JSONL, PDF, TXT) without "
        "specifying the format. Auto-detects format, delimiter, encoding, and header. "
        "For tabular files returns columns, rows, row_count, and sample_rows (first 20). "
        "For PDFs returns pages. Use instead of connector.loan_tape when the file format "
        "is unknown or non-standard. The sample_rows field feeds extractor.schema_inference."
    )
    inputs = {
        "path": "str: absolute path to the file to load.",
        "max_rows": "int, optional: max rows to return for tabular files (default 10000).",
    }
    outputs = {
        "payload.document": "str: filename.",
        "payload.detected_format": "str: csv|tsv|xlsx|json|jsonl|pdf|txt.",
        "payload.columns": "list[str]: column names (tabular only).",
        "payload.rows": "list[dict]: all rows up to max_rows (tabular only).",
        "payload.row_count": "int: total rows in file (tabular only).",
        "payload.sample_rows": "list[dict]: first 20 rows (tabular only).",
        "payload.has_header": "bool: whether row 0 was treated as header (tabular only).",
        "payload.detected_delimiter": "str: detected delimiter character (CSV/TSV only).",
        "payload.detected_encoding": "str: detected file encoding.",
        "payload.pages": "list[{page:int, text:str}]: pages (PDF/TXT only).",
        "payload.page_count": "int: number of pages (PDF/TXT only).",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        path_str: str = str(inp.get("path", "") or "").strip()
        max_rows: int = int(inp.get("max_rows", _MAX_ROWS) or _MAX_ROWS)

        if not path_str:
            return PrimitiveOutput(
                payload={"document": "", "detected_format": "unknown"},
                citations=[], confidence=0.0, issues=["path is required."],
            )

        path = pathlib.Path(path_str)
        if not path.exists():
            return PrimitiveOutput(
                payload={"document": path.name, "detected_format": "unknown"},
                citations=[], confidence=0.0, issues=[f"File not found: {path_str}"],
            )

        ext = path.suffix.lower().lstrip(".")
        document = path.name

        # PDF
        if ext == "pdf":
            return self._load_pdf(path, document)

        # Text / Markdown
        if ext in ("txt", "md"):
            return self._load_text(path, document)

        # Tabular
        if ext in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", ""):
            return self._load_tabular(path, document, ext, max_rows)

        # Unknown extension — try tabular first, then text
        try:
            return self._load_tabular(path, document, "", max_rows)
        except Exception:
            return self._load_text(path, document)

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_tabular(
        self, path: pathlib.Path, document: str, ext: str, max_rows: int
    ) -> PrimitiveOutput:
        import pandas as pd

        encoding, raw_bytes = _detect_encoding(path)

        if ext in ("xlsx", "xls"):
            df_full = pd.read_excel(str(path), engine="openpyxl", nrows=max_rows)
            detected_format = "xlsx"
            delimiter = None
            has_header = True
        elif ext in ("json",):
            text = raw_bytes.decode(encoding, errors="replace")
            obj = json.loads(text)
            if isinstance(obj, list):
                df_full = pd.DataFrame(obj[:max_rows])
            elif isinstance(obj, dict):
                # Wrap single object as one-row table or return as text
                df_full = pd.DataFrame([obj])
            detected_format = "json"
            delimiter = None
            has_header = True
        elif ext == "jsonl":
            lines = raw_bytes.decode(encoding, errors="replace").splitlines()
            rows_parsed = [json.loads(line) for line in lines[:max_rows] if line.strip()]
            df_full = pd.DataFrame(rows_parsed)
            detected_format = "jsonl"
            delimiter = None
            has_header = True
        else:
            # CSV / TSV / unknown text-based tabular
            text = raw_bytes.decode(encoding, errors="replace")
            delimiter = _detect_delimiter(text)
            has_header = _detect_header(text, delimiter)
            header_row = 0 if has_header else None
            df_full = pd.read_csv(
                io.StringIO(text),
                delimiter=delimiter,
                header=header_row,
                nrows=max_rows,
                low_memory=False,
            )
            if not has_header:
                df_full.columns = [f"col_{i}" for i in range(len(df_full.columns))]
            detected_format = "tsv" if delimiter == "\t" else "csv"

        # Clean up: NaN → None for JSON-serializable output
        df_full = df_full.where(df_full.notna(), other=None)
        columns = [str(c) for c in df_full.columns.tolist()]
        all_rows = df_full.to_dict(orient="records")
        sample_rows = all_rows[:_SAMPLE_ROWS]
        row_count = len(all_rows)

        citations = [
            Citation(source=document, location="row=0", excerpt=str(sample_rows[0])[:200])
        ] if sample_rows else []

        return PrimitiveOutput(
            payload={
                "document": document,
                "detected_format": detected_format,
                "detected_delimiter": delimiter,
                "detected_encoding": encoding,
                "has_header": has_header,
                "columns": columns,
                "rows": all_rows,
                "row_count": row_count,
                "sample_rows": sample_rows,
            },
            citations=citations,
            confidence=1.0,
            issues=[],
            metadata={"row_count": row_count, "column_count": len(columns)},
        )

    @staticmethod
    def _load_pdf(path: pathlib.Path, document: str) -> PrimitiveOutput:
        from ._pdf import extract_pages  # shared PDF extraction helper
        try:
            pages = list(extract_pages(path))
        except ImportError:
            # Fall back to direct pypdf usage
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                pages = [
                    {"page": i + 1, "text": (page.extract_text() or "")}
                    for i, page in enumerate(reader.pages)
                ]
            except Exception as exc:
                return PrimitiveOutput(
                    payload={"document": document, "detected_format": "pdf"},
                    citations=[], confidence=0.0, issues=[f"PDF load failed: {exc}"],
                )

        citations = [
            Citation(source=document, location="page=1", excerpt=pages[0]["text"][:200])
        ] if pages else []

        return PrimitiveOutput(
            payload={
                "document": document,
                "detected_format": "pdf",
                "detected_encoding": "binary",
                "pages": pages,
                "page_count": len(pages),
            },
            citations=citations,
            confidence=1.0,
            issues=[],
            metadata={"page_count": len(pages)},
        )

    @staticmethod
    def _load_text(path: pathlib.Path, document: str) -> PrimitiveOutput:
        encoding, raw_bytes = _detect_encoding(path)
        text = raw_bytes.decode(encoding, errors="replace")
        # Split into ~1000-char pages so downstream page-based extractors work
        chunk_size = 1000
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        pages = [{"page": i + 1, "text": chunk} for i, chunk in enumerate(chunks)]

        return PrimitiveOutput(
            payload={
                "document": document,
                "detected_format": path.suffix.lower().lstrip(".") or "txt",
                "detected_encoding": encoding,
                "pages": pages,
                "page_count": len(pages),
            },
            citations=[Citation(source=document, location="page=1", excerpt=text[:200])],
            confidence=1.0,
            issues=[],
            metadata={"page_count": len(pages)},
        )


# ------------------------------------------------------------------
# Detection helpers
# ------------------------------------------------------------------

def _detect_encoding(path: pathlib.Path) -> tuple[str, bytes]:
    """Return (encoding, raw_bytes) using a UTF-8 → Latin-1 fallback chain."""
    raw = path.read_bytes()
    # BOM detection
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", raw
    # Try chardet if available
    try:
        import chardet
        detected = chardet.detect(raw[:10_000])
        enc = (detected.get("encoding") or "utf-8").lower()
        raw.decode(enc)
        return enc, raw
    except Exception:
        pass
    # Fallback chain
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            raw.decode(enc)
            return enc, raw
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1", raw


def _detect_delimiter(text: str) -> str:
    """Sniff the CSV delimiter from the first 3 lines."""
    lines = [l for l in text.splitlines()[:3] if l.strip()]
    if not lines:
        return ","
    candidates = [",", ";", "\t", "|"]
    scores = {d: sum(line.count(d) for line in lines) for d in candidates}
    return max(scores, key=lambda d: scores[d])


def _detect_header(text: str, delimiter: str) -> bool:
    """Heuristic: row 0 is a header if it has more string tokens than row 1."""
    lines = [l for l in text.splitlines()[:2] if l.strip()]
    if len(lines) < 2:
        return True
    def _string_ratio(line: str) -> float:
        tokens = line.split(delimiter)
        if not tokens:
            return 0.0
        str_count = sum(1 for t in tokens if not _looks_numeric(t.strip()))
        return str_count / len(tokens)
    return _string_ratio(lines[0]) > _string_ratio(lines[1])


def _looks_numeric(token: str) -> bool:
    try:
        float(token.replace(",", "").replace("%", ""))
        return True
    except ValueError:
        return False
