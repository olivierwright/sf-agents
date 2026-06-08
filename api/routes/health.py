"""GET /api/health — liveness probe with environment info.
GET /api/warmup — prewarm connectors (pypdf caches + pandas header reads).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    data_dir = Path(os.environ.get("SF_AGENTS_DATA_DIR", "Sample Data"))
    deal_loaded = (data_dir / "green_lion_2026_1_synthetic_loan_tape.csv").exists()
    return {
        "status": "ok",
        "model": os.environ.get("SF_AGENTS_MODEL", "anthropic.claude-sonnet-4-20250514-v1:0"),
        "region": os.environ.get("SF_AGENTS_REGION", "eu-north-1"),
        "deal_loaded": deal_loaded,
    }


@router.get("/warmup")
async def warmup() -> dict:
    """Prewarm connectors by reading each PDF (page count only) and tape header.

    Call once after server start to populate pypdf and pandas internal caches.
    Eliminates the 20-30 s cold-start penalty on the first Demo Day question.
    Returns {"status": "warm", "files_loaded": N, "duration_ms": N}.
    """
    t0 = time.monotonic()
    files_loaded = 0
    errors: list[str] = []

    data_dir = Path(os.environ.get("SF_AGENTS_DATA_DIR", "Sample Data"))

    # Warm PDF parsing — read page counts only, not content
    try:
        from pypdf import PdfReader
        pdf_available = True
    except ImportError:
        pdf_available = False
        errors.append("pypdf not installed — PDF warmup skipped")

    if pdf_available:
        for pdf_path in sorted(data_dir.glob("*.pdf")):
            try:
                reader = PdfReader(str(pdf_path))
                _ = len(reader.pages)
                files_loaded += 1
            except Exception as exc:
                errors.append(f"{pdf_path.name}: {exc}")

    # Warm tape parsing — header + 1 row only
    try:
        import pandas as pd
        for csv_path in sorted(data_dir.glob("*.csv")):
            try:
                pd.read_csv(str(csv_path), nrows=1)
                files_loaded += 1
            except Exception as exc:
                errors.append(f"{csv_path.name}: {exc}")
    except ImportError:
        errors.append("pandas not installed — tape warmup skipped")

    # Also pre-populate the deal summary cache (page counts + tape stats)
    try:
        from api.routes.deal import _load_pdf_page_counts, _load_summary
        _load_pdf_page_counts()
        _load_summary()
        files_loaded += 1
    except Exception:
        pass  # best-effort

    duration_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "status": "warm",
        "files_loaded": files_loaded,
        "duration_ms": duration_ms,
        "errors": errors,
    }
