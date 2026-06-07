"""GET /api/deal/periods — month-over-month comparison across loan tape periods."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _find_tape_files() -> list[Path]:
    """Discover all monthly loan tape CSVs in Sample Data/."""
    data_dir = Path("Sample Data")
    if not data_dir.exists():
        return []
    tapes = sorted(data_dir.glob("green_lion_*_synthetic_loan_tape.csv"))
    return tapes


def _load_period(tape_path: Path) -> dict[str, Any]:
    """Load a single loan tape and return minimal stats for comparison."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for period comparison") from exc

    df = pd.read_csv(tape_path)

    # Extract reporting date
    reporting_date = ""
    if "reporting_date" in df.columns:
        reporting_date = str(df["reporting_date"].iloc[0])

    # Balance
    total_balance = float(df["current_balance"].sum()) if "current_balance" in df.columns else 0
    avg_balance = float(df["current_balance"].mean()) if "current_balance" in df.columns else 0

    # Rates
    avg_rate = float(df["current_interest_rate_pct"].mean()) if "current_interest_rate_pct" in df.columns else 0

    # Weighted average rate
    weighted_avg_rate = avg_rate
    if "current_balance" in df.columns and "current_interest_rate_pct" in df.columns:
        weights = df["current_balance"].fillna(0)
        rates = df["current_interest_rate_pct"].fillna(0)
        total_w = weights.sum()
        if total_w > 0:
            weighted_avg_rate = float((weights * rates).sum() / total_w)

    # Performance
    loan_count = len(df)
    performing_count = int((df["performing_status"] == "Non-defaulted").sum()) if "performing_status" in df.columns else loan_count
    performing_pct = round(performing_count / loan_count * 100, 2) if loan_count > 0 else 0

    arrears_count = int((df["arrears_bucket"] != "Performing").sum()) if "arrears_bucket" in df.columns else 0
    arrears_pct = round(arrears_count / loan_count * 100, 2) if loan_count > 0 else 0

    # Green
    green_labels = {"A", "A+", "A++", "A+++", "B"}
    green_count = int(df["epc_label"].isin(green_labels).sum()) if "epc_label" in df.columns else 0
    green_pct = round(green_count / loan_count * 100, 2) if loan_count > 0 else 0

    # LTV
    avg_ltv = float(df["cltomv_current"].mean()) if "cltomv_current" in df.columns else 0

    # EPC distribution
    epc_breakdown: dict[str, int] = {}
    if "epc_label" in df.columns:
        epc_breakdown = {str(k): int(v) for k, v in df["epc_label"].value_counts().sort_index().items()}

    # Arrears breakdown
    arrears_breakdown: dict[str, int] = {}
    if "arrears_bucket" in df.columns:
        arrears_breakdown = {str(k): int(v) for k, v in df["arrears_bucket"].value_counts().sort_index().items()}

    # Rate type breakdown
    rate_type_breakdown: dict[str, int] = {}
    if "rate_type" in df.columns:
        rate_type_breakdown = {str(k): int(v) for k, v in df["rate_type"].value_counts().sort_index().items()}

    return {
        "file": tape_path.name,
        "reporting_date": reporting_date,
        "metrics": {
            "loan_count": loan_count,
            "total_balance": round(total_balance, 2),
            "avg_balance": round(avg_balance, 2),
            "avg_interest_rate_pct": round(avg_rate, 4),
            "weighted_avg_rate": round(weighted_avg_rate, 4),
            "performing_pct": performing_pct,
            "arrears_pct": arrears_pct,
            "green_label_pct": green_pct,
            "avg_ltv": round(avg_ltv, 2),
        },
        "distributions": {
            "epc_label": epc_breakdown,
            "arrears_bucket": arrears_breakdown,
            "rate_type": rate_type_breakdown,
        },
    }


def _pct_change(old: float, new: float) -> float | None:
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 2)


@router.get("/deal/periods")
async def deal_periods() -> dict[str, Any]:
    """Return month-over-month comparison data for all available tape periods."""
    tape_files = _find_tape_files()
    if not tape_files:
        raise HTTPException(status_code=404, detail="No loan tape files found in Sample Data/")

    periods = []
    for tape in tape_files:
        try:
            periods.append(_load_period(tape))
        except Exception as exc:
            continue  # skip unreadable files

    if len(periods) < 1:
        raise HTTPException(status_code=404, detail="Could not load any tape files")

    # Sort by reporting date
    periods.sort(key=lambda p: p["reporting_date"])

    # Build comparison metrics with changes
    period_labels = [p["reporting_date"] for p in periods]
    metric_names = list(periods[0]["metrics"].keys())

    metrics_comparison: dict[str, dict] = {}
    for metric in metric_names:
        values = [p["metrics"][metric] for p in periods]
        changes: list[float | None] = [None]
        for i in range(1, len(values)):
            changes.append(_pct_change(values[i - 1], values[i]))
        metrics_comparison[metric] = {"values": values, "changes_pct": changes}

    # Identify highlights (>5% change)
    highlights = []
    for metric, data in metrics_comparison.items():
        for i, change in enumerate(data["changes_pct"]):
            if change is not None and abs(change) > 5.0:
                highlights.append({
                    "metric": metric,
                    "period": period_labels[i],
                    "direction": "increase" if change > 0 else "decrease",
                    "magnitude_pct": round(abs(change), 1),
                    "from_value": data["values"][i - 1],
                    "to_value": data["values"][i],
                })
    highlights.sort(key=lambda h: h["magnitude_pct"], reverse=True)

    # Chart-ready data
    chart_data = {
        "bar": {
            "labels": period_labels,
            "datasets": [
                {"label": "Total Balance (EUR)", "data": metrics_comparison["total_balance"]["values"]},
                {"label": "Loan Count", "data": metrics_comparison["loan_count"]["values"]},
            ],
        },
        "line": {
            "labels": period_labels,
            "datasets": [
                {"label": "Avg Interest Rate (%)", "data": metrics_comparison["avg_interest_rate_pct"]["values"]},
                {"label": "Performing (%)", "data": metrics_comparison["performing_pct"]["values"]},
                {"label": "Green Label (%)", "data": metrics_comparison["green_label_pct"]["values"]},
                {"label": "Avg LTV (%)", "data": metrics_comparison["avg_ltv"]["values"]},
            ],
        },
        "distributions": {p["reporting_date"]: p["distributions"] for p in periods},
    }

    return {
        "periods": period_labels,
        "files": [p["file"] for p in periods],
        "metrics": metrics_comparison,
        "highlights": highlights,
        "chart_data": chart_data,
        "distributions": {p["reporting_date"]: p["distributions"] for p in periods},
    }
