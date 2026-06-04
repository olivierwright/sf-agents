"""GET /api/primitives — live primitive catalogue from the registry."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sf_agents.orchestrator.registry import build_default_registry

router = APIRouter()


@router.get("/primitives")
async def list_primitives() -> list[dict]:
    """Return the full primitive catalogue with input/output contracts."""
    registry = build_default_registry()
    return registry.describe()


@router.get("/primitives/{name:path}/schema")
async def primitive_schema(name: str) -> dict:
    """Return the full describe() dict for a single primitive."""
    registry = build_default_registry()
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown primitive: {name!r}")
    return registry._descriptions[name]
