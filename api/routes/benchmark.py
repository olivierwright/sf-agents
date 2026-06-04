"""POST /api/benchmark — run the same question through multiple strategies in parallel."""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..routes.runs import _get_recipe_context, _run_question_worker
from ..streaming import run_store

router = APIRouter()

_VALID_STRATEGIES = {"thorough", "minimal", "parallel_first"}


class BenchmarkRequest(BaseModel):
    """Body for POST /api/benchmark."""

    question: str
    strategies: list[str] = ["thorough", "minimal", "parallel_first"]
    documents: dict[str, str] | None = None


@router.post("/benchmark", status_code=202)
async def create_benchmark(body: BenchmarkRequest) -> dict:
    """Spawn one run per strategy and return their IDs for parallel comparison."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="'question' must not be blank.")

    invalid = [s for s in body.strategies if s not in _VALID_STRATEGIES]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown strategies: {invalid}. Valid: {sorted(_VALID_STRATEGIES)}",
        )

    documents = body.documents or {}
    context = {"documents": documents} if documents else {}
    loop = asyncio.get_running_loop()

    runs = []
    for strategy in body.strategies:
        record = run_store.create(question=question, strategy=strategy)
        thread = threading.Thread(
            target=_run_question_worker,
            args=(record.run_id, question, strategy, context, None, loop, ""),
            daemon=True,
            name=f"sf-bench-{strategy[:4]}-{record.run_id[:6]}",
        )
        thread.start()
        runs.append(
            {
                "strategy": strategy,
                "run_id": record.run_id,
                "stream_url": f"/api/runs/{record.run_id}/stream",
                "result_url": f"/api/runs/{record.run_id}/result",
            }
        )

    return {"question": question, "runs": runs}
