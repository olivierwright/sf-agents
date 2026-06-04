"""Pydantic models for the API layer.

These mirror the stdlib-dataclass models in sf_agents.orchestrator.events but
use Pydantic so FastAPI can serialise them directly into SSE JSON payloads.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunEventModel(BaseModel):
    """A single lifecycle event emitted during an agent run."""

    type: str
    payload: dict[str, Any]
    timestamp: str


class RunRequest(BaseModel):
    """Body for POST /api/runs.

    Two modes:
    - Recipe shortcut: supply ``recipe`` (backward compat).
    - Free-form: supply ``question`` + optional ``strategy`` and ``documents``.
    """

    recipe: str | None = Field(
        default=None,
        description="Recipe shortcut: 'definition_transparency' or 'impact_mapping'.",
    )
    question: str | None = Field(
        default=None,
        description="Free-form natural-language question to answer against deal documents.",
    )
    strategy: str = Field(
        default="thorough",
        description="Orchestration strategy: 'thorough' | 'minimal' | 'parallel_first'.",
    )
    documents: dict[str, str] | None = Field(
        default=None,
        description="Document paths keyed by role, e.g. {'prospectus': '/path/to/file.pdf'}.",
    )
    run_id: str | None = Field(
        default=None,
        description="Optional caller-supplied run ID (UUID generated server-side if absent).",
    )


class RunStatus(BaseModel):
    """Snapshot of a run's current status, returned by GET /api/runs/{id}/result."""

    run_id: str
    recipe: str = ""
    question: str = ""
    strategy: str = "thorough"
    status: str  # "pending" | "running" | "done" | "error"
    result: dict[str, Any] | None = None
    error: str | None = None
