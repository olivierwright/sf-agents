"""Tested, versioned building blocks ("primitives") of sf-agents.

Public contracts live in :mod:`sf_agents.primitives.base`. Concrete primitives
are grouped by role: ``connectors``, ``extractors``, ``validators`` and
``analyzers``. The Bedrock boundary lives in the private :mod:`._llm` module --
nothing else in the package may import ``boto3``.
"""

from .base import (
    AuditRecord,
    BasePrimitive,
    Citation,
    PrimitiveInput,
    PrimitiveOutput,
)

__all__ = [
    "AuditRecord",
    "BasePrimitive",
    "Citation",
    "PrimitiveInput",
    "PrimitiveOutput",
]
