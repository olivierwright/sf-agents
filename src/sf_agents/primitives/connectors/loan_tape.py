"""Connector for the synthetic loan tapes (ESMA-style RMBS line items).

Format-agnostic: detects ``.csv`` vs ``.xlsx``/``.xls`` by file extension and
reads with pandas accordingly. The real sample tapes in this repo are CSV; the
XLSX path is kept ready for future tapes delivered in that format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput


class LoanTapeConnector(BasePrimitive):
    """Load a loan tape (CSV or XLSX) into column metadata + row records.

    Input args:
        path (str): Path to the loan tape file (``.csv``, ``.xlsx`` or ``.xls``).
        max_rows (int, optional): Cap on rows returned (default: all).

    Payload:
        ``{"document": <name>, "columns": [...], "rows": [ {col: val}... ],
           "row_count": int}``
    """

    name = "connector.loan_tape"
    version = "0.1.0"
    capability = (
        "Load a loan-level tape (CSV or XLSX) into its column schema and row "
        "records. Use this to inspect how terms such as arrears, default and "
        "performing-status are operationalised as actual loan-level fields "
        "(e.g. arrears_bucket, days_past_due, default_crr_flag, performing_status)."
    )
    inputs = {
        "path": "str: filesystem path to the loan tape CSV/XLSX (a literal from context.documents.loan_tape).",
        "max_rows": "int, optional: cap on rows returned (omit for all rows).",
    }
    outputs = {
        "payload.document": "str: the tape file name.",
        "payload.columns": "list[str]: column names; feed to validator.esma_schema as its 'columns' arg.",
        "payload.rows": "list[dict]: row records; feed to validator.esma_schema as its 'rows' arg.",
        "payload.row_count": "int: number of rows.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        path = Path(inp.get("path", ""))
        if not path.exists():
            raise FileNotFoundError(f"Loan tape not found: {path}")
        max_rows = inp.get("max_rows")

        frame = self._read(path)
        if max_rows is not None:
            frame = frame.head(int(max_rows))

        columns = [str(c) for c in frame.columns]
        # Records with native python types; NaN -> None for clean JSON/audit.
        rows: list[dict[str, Any]] = [
            {k: (None if _is_nan(v) else v) for k, v in record.items()}
            for record in frame.to_dict(orient="records")
        ]

        citations = []
        if rows:
            first_id = rows[0].get("loan_id", "?")
            citations.append(
                Citation(
                    source=path.name,
                    location="row=0",
                    excerpt=f"loan_id={first_id}; {len(columns)} columns",
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
        """Read CSV or Excel into a DataFrame based on file extension."""
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("pandas is required to read loan tapes.") from exc

        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, engine="openpyxl")
        raise ValueError(
            f"Unsupported loan-tape format {suffix!r}; expected .csv, .xlsx or .xls."
        )


def _is_nan(value: Any) -> bool:
    """True only for genuine float NaN (avoids importing pandas at call sites)."""
    return isinstance(value, float) and value != value
