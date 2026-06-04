"""sf-agents: an open, governance-first structured-finance agent framework.

The framework pairs **fixed, tested primitives** (connectors, extractors,
validators, analyzers) with a **dynamic LLM orchestrator** (planner, executor,
verifier). Every primitive returns citations + confidence + issues, every call
is recorded to an append-only audit log, and every citation is verified to
resolve to a real source chunk before a result is trusted.
"""

from .config import Config, get_config

__all__ = ["Config", "get_config", "__version__"]
__version__ = "0.1.0"
