"""Connector for period-level remittance and trustee cashflow files.

Format-agnostic: detects ``.csv`` vs ``.xlsx``/``.xls`` by extension and reads
with pandas. Citations anchor the loaded time range: one on the first row and
one on the last row so the verifier can confirm coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput


class RemittanceFileConnector(BasePrimitive):
    """Load a remittance or trustee report file into column metadata and rows.

    Input args:
        path (str): Path to the file (``.csv``, ``.xlsx`` or ``.xls``).
        max_rows (int, optional): Cap on rows returned (default: all).

    Payload:
        ``{"document": <name>, "columns": [...], "rows": [{col: val}...],
           "row_count": int}``
    """

    name = "connector.remittance_file"
    version = "0.1.0"
    capability = (
        "Load a remittance or trustee report file (CSV or XLSX ONLY — NOT PDF) "
        "containing period-level cashflow figures such as collections, interest, and "
        "principal. ONLY use this primitive when context.documents contains a key "
        "whose path ends in .csv, .xlsx, or .xls. Never pass a PDF path to this "
        "primitive. Use this before analyzer.cashflow_anomaly."
    )
    inputs = {
        "path": "str: filesystem path to the remittance CSV/XLSX file.",
        "max_rows": "int, optional: cap on rows returned (omit for all rows).",
    }
    outputs = {
        "payload.document": "str: the file name.",
        "payload.columns": "list[str]: column names.",
        "payload.rows": "list[dict]: row records keyed by column name.",
        "payload.row_count": "int: number of period rows loaded.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        path = Path(inp.get("path", ""))
        if not path.exists():
            raise FileNotFoundError(f"Remittance file not found: {path}")
        max_rows = inp.get("max_rows")

        frame = self._read(path)
        if max_rows is not None:
            frame = frame.head(int(max_rows))

        columns = [str(c) for c in frame.columns]
        rows: list[dict[str, Any]] = [
            {k: (None if _is_nan(v) else v) for k, v in record.items()}
            for record in frame.to_dict(orient="records")
        ]

        citations: list[Citation] = []
        if rows:
            # Anchor first period
            first_period = _first_date_value(rows[0])
            citations.append(
                Citation(
                    source=path.name,
                    location="row=0",
                    excerpt=f"first period: {first_period}; {len(columns)} columns",
                )
            )
            if len(rows) > 1:
                # Anchor last period to show time range coverage
                last_period = _first_date_value(rows[-1])
                citations.append(
                    Citation(
                        source=path.name,
                        location=f"row={len(rows) - 1}",
                        excerpt=f"last period: {last_period}",
                    )
                )

        return PrimitiveOutput(
            payload={
                "document": path.name,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            },
            citations=citations,
            confidence=1.0,
            issues=[],
            metadata={"format": path.suffix.lower().lstrip("."), "path": str(path)},
        )

    @staticmethod
    def _read(path: Path):
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pandas is required to read remittance files.") from exc

        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, engine="openpyxl")
        raise ValueError(
            f"Unsupported format {suffix!r}; expected .csv, .xlsx or .xls."
        )


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and value != value


def _first_date_value(row: dict[str, Any]) -> str:
    """Return the first non-None value from date-like columns, or '?'."""
    date_keys = [k for k in row if any(d in k.lower() for d in ("date", "period", "month"))]
    for k in date_keys:
        if row[k] is not None:
            return str(row[k])
    # Fall back to the very first non-None value
    for v in row.values():
        if v is not None:
            return str(v)
    return "?"
