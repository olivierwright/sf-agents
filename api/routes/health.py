"""GET /api/health — liveness probe with environment info."""

from __future__ import annotations

import os
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
