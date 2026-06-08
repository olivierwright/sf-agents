"""GET /api/deal — summary statistics for the Green Lion deal."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@functools.lru_cache(maxsize=1)
def _load_pdf_page_counts() -> dict[str, int]:
    """Read page counts from all PDFs in Sample Data/ once at startup.

    Returns a dict mapping filename -> page count. Uses pypdf; silently
    returns 0 for any PDF that cannot be read (scanned/locked).
    """
    data_dir = Path("Sample Data")
    counts: dict[str, int] = {}
    try:
        from pypdf import PdfReader
    except ImportError:
        return counts

    for pdf_path in data_dir.glob("*.pdf"):
        try:
            reader = PdfReader(str(pdf_path))
            counts[pdf_path.name] = len(reader.pages)
        except Exception:
            counts[pdf_path.name] = 0
    return counts


@functools.lru_cache(maxsize=1)
def _load_summary() -> dict[str, Any]:
    """Read the loan tape once and compute summary stats."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for /api/deal") from exc

    data_dir = Path("Sample Data")
    tape_path = data_dir / "green_lion_2026_1_synthetic_loan_tape.csv"
    if not tape_path.exists():
        raise FileNotFoundError(f"Loan tape not found: {tape_path}")

    df = pd.read_csv(tape_path)

    # EPC breakdown
    epc_counts: dict[str, int] = {}
    if "epc_label" in df.columns:
        epc_counts = {
            str(k): int(v)
            for k, v in df["epc_label"].value_counts().sort_index().items()
        }

    # Performance breakdown
    performing_counts: dict[str, int] = {}
    if "performing_status" in df.columns:
        performing_counts = {
            str(k): int(v)
            for k, v in df["performing_status"].value_counts().items()
        }

    arrears_buckets: dict[str, int] = {}
    if "arrears_bucket" in df.columns:
        arrears_buckets = {
            str(k): int(v)
            for k, v in df["arrears_bucket"].value_counts().sort_index().items()
        }

    # Vintage
    vintage: dict[str, int] = {}
    if "origination_year" in df.columns:
        vintage = {
            str(int(k)): int(v)
            for k, v in df["origination_year"].value_counts().sort_index().items()
        }

    # Green metrics
    green_pct: float | None = None
    if "epc_label" in df.columns:
        green_labels = {"A", "A+", "A++", "A+++", "B"}
        green_count = int(df["epc_label"].isin(green_labels).sum())
        green_pct = round(green_count / len(df) * 100, 1)

    construction_deposit_pct: float | None = None
    if "construction_deposit_flag" in df.columns:
        yes_count = int((df["construction_deposit_flag"] == "Y").sum())
        construction_deposit_pct = round(yes_count / len(df) * 100, 1)

    total_balance_eur: float | None = None
    if "current_balance" in df.columns:
        total_balance_eur = round(float(df["current_balance"].sum()), 2)

    avg_current_rate: float | None = None
    if "current_interest_rate_pct" in df.columns:
        avg_current_rate = round(float(df["current_interest_rate_pct"].mean()), 4)

    transaction_name: str | None = None
    if "transaction_name" in df.columns:
        transaction_name = str(df["transaction_name"].iloc[0])

    reporting_date: str | None = None
    if "reporting_date" in df.columns:
        reporting_date = str(df["reporting_date"].iloc[0])

    # Real page counts from PDFs (read once, cached)
    page_counts = _load_pdf_page_counts()

    def _pages(filename: str) -> int:
        return page_counts.get(filename, 0) or 0

    return {
        "deal": {
            "name": transaction_name or "Green Lion 2026-1",
            "reporting_date": reporting_date,
            "currency": "EUR",
        },
        "portfolio": {
            "loan_count": int(len(df)),
            "total_balance_eur": total_balance_eur,
            "avg_interest_rate_pct": avg_current_rate,
        },
        "green": {
            "epc_breakdown": epc_counts,
            "green_label_pct": green_pct,
            "construction_deposit_pct": construction_deposit_pct,
        },
        "performance": {
            "performing_status": performing_counts,
            "arrears_buckets": arrears_buckets,
        },
        "vintage": vintage,
        "documents": [
            {
                "name": "Green Lion 2026-1 Prospectus",
                "type": "prospectus",
                "pages": _pages("green-lion-2026-1-prospectus.pdf"),
                "file": "green-lion-2026-1-prospectus.pdf",
            },
            {
                "name": "Monthly Investor Report (April 2026)",
                "type": "investor_report",
                "pages": _pages("monthly-investor-report-green-lion-2026-1-april-2026.pdf"),
                "file": "monthly-investor-report-green-lion-2026-1-april-2026.pdf",
            },
            {
                "name": "ISS Second Party Opinion",
                "type": "spo",
                "pages": _pages("green-lion-2026-1-iss-second-party-opinion-spo.pdf"),
                "file": "green-lion-2026-1-iss-second-party-opinion-spo.pdf",
            },
            {
                "name": "CFP Impact Report",
                "type": "impact_report",
                "pages": _pages("green-lion-2026-1-cfp-impact-report.pdf"),
                "file": "green-lion-2026-1-cfp-impact-report.pdf",
            },
        ],
        "tape": {
            # Exact column names from the real tape
            "key_green_fields": [
                "epc_label",
                "epc_issue_year",
                "primary_energy_demand_kwh_m2",
                "construction_deposit_flag",
            ],
        },
    }


@router.get("/deal")
async def deal_summary() -> dict[str, Any]:
    try:
        return _load_summary()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
