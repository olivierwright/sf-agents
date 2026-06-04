"""Core contracts every primitive in sf-agents must honour.

This module defines the shared data shapes -- :class:`Citation`,
:class:`PrimitiveInput`, :class:`PrimitiveOutput`, :class:`AuditRecord` -- and
the :class:`BasePrimitive` abstract base class. ``BasePrimitive.__call__`` wraps
the concrete ``run`` implementation with timing and an audit hook so that *every*
primitive call produces governance evidence, with no extra effort from authors.

Design rules (non-negotiable, see README):
    * A primitive never returns a bare string. It returns a ``PrimitiveOutput``
      carrying ``payload``, ``citations``, ``confidence``, ``issues`` and
      ``metadata``.
    * Every call is timed and offered to an audit hook.
    * ``name``, ``version`` and ``capability`` are declared as class attributes;
      the ``capability`` string is what the planner reads when composing a plan.
"""

from __future__ import annotations

import abc
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# --------------------------------------------------------------------------- #
# Citation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Citation:
    """A pointer back to the exact source evidence for a claim.

    Attributes:
        source: Logical source identifier (e.g. a file name or document id).
        location: Where inside the source (e.g. ``"page=42"`` or ``"row=17"``).
            The verifier parses this to confirm the location truly exists.
        excerpt: The literal text/value lifted from the source.
    """

    source: str
    location: str
    excerpt: str

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "location": self.location, "excerpt": self.excerpt}


# --------------------------------------------------------------------------- #
# Primitive I/O
# --------------------------------------------------------------------------- #
@dataclass
class PrimitiveInput:
    """Input envelope passed to a primitive.

    Attributes:
        args: Free-form keyword arguments specific to the primitive.
        context: Shared, run-scoped context (e.g. upstream outputs keyed by step).
    """

    args: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.args.get(key, default)


@dataclass
class PrimitiveOutput:
    """The single, uniform return shape for every primitive.

    Attributes:
        payload: The primitive's structured result (never a bare string).
        citations: Evidence supporting the payload. May be empty for pure
            transforms, but cognitive/extraction primitives must populate it.
        confidence: A value in ``[0.0, 1.0]``. Outputs below the configured
            floor are routed to human review by the executor.
        issues: Human-readable problems, warnings or caveats discovered.
        metadata: Free-form diagnostic detail (token counts, paths, etc.).
    """

    payload: Any
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 1.0
    issues: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "payload": self.payload,
            "citations": [c.as_dict() for c in self.citations],
            "confidence": self.confidence,
            "issues": list(self.issues),
            "metadata": self.metadata,
        }


# --------------------------------------------------------------------------- #
# Audit record
# --------------------------------------------------------------------------- #
def _hash_obj(obj: Any) -> str:
    """Stable SHA-256 of an arbitrary JSON-able object (best-effort)."""
    try:
        blob = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    except (TypeError, ValueError):
        blob = repr(obj).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    """One append-only entry describing a single primitive invocation."""

    run_id: str
    step_id: str
    primitive: str
    version: str
    input_hash: str
    output_hash: str
    duration_ms: float
    confidence: float
    timestamp: str
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# A hook receives a finished AuditRecord. The audit logger registers one of these.
AuditHook = Callable[[AuditRecord], None]


# --------------------------------------------------------------------------- #
# BasePrimitive
# --------------------------------------------------------------------------- #
class BasePrimitive(abc.ABC):
    """Abstract base for all primitives.

    Subclasses set the class attributes ``name``, ``version`` and ``capability``
    and implement :meth:`run`. Callers invoke the instance (``primitive(inp)``);
    :meth:`__call__` handles timing and audit emission so :meth:`run` can stay
    focused on the actual work.
    """

    #: Unique, stable identifier used by the registry and planner.
    name: str = "base"
    #: Semantic version of this primitive's contract/behaviour.
    version: str = "0.0.0"
    #: One-line, planner-facing description of what this primitive can do.
    capability: str = "Abstract base primitive; do not register."
    #: Planner-facing input contract: arg name -> short description. The planner
    #: must use exactly these arg names (no more, no fewer).
    inputs: dict[str, str] = {}
    #: Planner-facing output contract: ``payload.<field>`` paths this primitive
    #: emits, so a downstream step can reference them via ``$from``/``path``.
    outputs: dict[str, str] = {}

    def __init__(self, audit_hook: Optional[AuditHook] = None) -> None:
        """Create a primitive, optionally wired to an audit hook."""
        self._audit_hook = audit_hook

    # -- public API -------------------------------------------------------- #
    @abc.abstractmethod
    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        """Do the work. Subclasses implement this; callers use ``__call__``."""
        raise NotImplementedError

    def __call__(
        self,
        inp: PrimitiveInput,
        *,
        run_id: str = "adhoc",
        step_id: str = "step",
    ) -> PrimitiveOutput:
        """Execute :meth:`run` with timing and audit emission.

        Args:
            inp: The primitive input envelope.
            run_id: Identifier for the overall run (set by the executor).
            step_id: Identifier for this step within the run.

        Returns:
            The :class:`PrimitiveOutput` produced by :meth:`run`.
        """
        start = time.perf_counter()
        output = self.run(inp)
        duration_ms = (time.perf_counter() - start) * 1000.0

        record = AuditRecord(
            run_id=run_id,
            step_id=step_id,
            primitive=self.name,
            version=self.version,
            input_hash=_hash_obj({"args": inp.args}),
            output_hash=_hash_obj(output.payload),
            duration_ms=round(duration_ms, 3),
            confidence=float(output.confidence),
            timestamp=datetime.now(timezone.utc).isoformat(),
            issues=list(output.issues),
        )
        output.metadata.setdefault("audit", record.as_dict())
        if self._audit_hook is not None:
            self._audit_hook(record)
        return output

    # -- introspection ----------------------------------------------------- #
    def describe(self) -> dict[str, Any]:
        """Return the planner-facing description of this primitive."""
        return {
            "name": self.name,
            "version": self.version,
            "capability": self.capability,
            "inputs": dict(self.inputs),
            "outputs": dict(self.outputs),
        }
