"""Dynamic orchestration: registry, planner, executor, verifier.

The orchestrator turns a natural-language question into an inspectable JSON DAG
of registered primitives (``planner``), runs that DAG with dependency
resolution, retries and human-review routing (``executor``), and proves that
every citation resolves to a real source chunk (``verifier``). The
:class:`Registry` is the catalogue the planner is allowed to choose from.
"""

from .registry import Registry, build_default_registry
from .planner import Plan, Planner, Step
from .executor import ExecutionResult, Executor
from .verifier import VerificationReport, Verifier
from .events import EventType, OnEvent, RunEvent

__all__ = [
    "Registry",
    "build_default_registry",
    "Plan",
    "Planner",
    "Step",
    "ExecutionResult",
    "Executor",
    "VerificationReport",
    "Verifier",
    "EventType",
    "OnEvent",
    "RunEvent",
]
