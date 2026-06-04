"""GET /api/use-cases — discovery catalogue of structured-finance use cases.

These are *inspiration templates* — clicking one pre-fills the UI question field.
Execution always goes through the dynamic orchestrator, not a hardcoded path.
"""

from __future__ import annotations

from fastapi import APIRouter

from sf_agents.use_cases.catalog import USE_CASES

router = APIRouter()


@router.get("/use-cases")
async def list_use_cases() -> list[dict]:
    """Return discovery catalogue of structured-finance use cases."""
    return USE_CASES
