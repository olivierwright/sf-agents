"""Recipes: end-to-end, runnable analyses composed from primitives.

A recipe wires the orchestrator (registry -> planner -> executor -> verifier)
around a concrete question and the real Green Lion sample data. It is the unit a
demo (or another team) actually runs.
"""

from .definition_transparency import (
    build_fallback_plan,
    run_definition_transparency,
)

__all__ = ["build_fallback_plan", "run_definition_transparency"]
