"""GET /api/strategies — list of available orchestration strategies."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

_STRATEGIES = [
    {
        "id": "thorough",
        "label": "Thorough",
        "description": (
            "LLM selects all relevant primitives for maximum coverage. "
            "Best for exploratory questions where you want comprehensive evidence."
        ),
    },
    {
        "id": "minimal",
        "label": "Minimal",
        "description": (
            "LLM given a cost-optimisation constraint: fewest steps that still "
            "produce a cited, verified answer. Best for focused questions with "
            "a known scope."
        ),
    },
    {
        "id": "parallel_first",
        "label": "Parallel First",
        "description": (
            "Executes the same plan as Thorough but annotates steps by "
            "topological wave so the UI shows which steps could run in parallel. "
            "Useful for understanding DAG structure and execution latency."
        ),
    },
]


@router.get("/strategies")
async def list_strategies() -> list[dict]:
    """Return available orchestration strategies."""
    return _STRATEGIES
