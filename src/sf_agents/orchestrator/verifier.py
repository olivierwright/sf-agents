"""The verifier: prove every citation resolves to a real source chunk.

The verifier walks every citation produced by every step and checks it against
the source index built during execution (document name -> valid pages / row
count). If any citation points at a page or row that does not exist -- a
hallucinated reference -- the run is marked failed. This is the framework's
trust anchor: no answer ships with an unverifiable citation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..governance.citation import parse_location
from ..primitives.base import PrimitiveOutput


@dataclass(frozen=True)
class CitationCheck:
    """The result of verifying a single citation."""

    step_id: str
    source: str
    location: str
    ok: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "source": self.source,
            "location": self.location,
            "ok": self.ok,
            "reason": self.reason,
        }


@dataclass
class VerificationReport:
    """Aggregate verification outcome for a run."""

    ok: bool
    checks: list[CitationCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[CitationCheck]:
        return [c for c in self.checks if not c.ok]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total": len(self.checks),
            "failures": [c.as_dict() for c in self.failures],
            "checks": [c.as_dict() for c in self.checks],
        }


class Verifier:
    """Verify citations across all step outputs against the source index."""

    def verify(
        self,
        outputs: dict[str, PrimitiveOutput],
        sources: dict[str, dict[str, Any]],
    ) -> VerificationReport:
        """Return a :class:`VerificationReport`; ``ok`` is False if any citation fails."""
        checks: list[CitationCheck] = []
        for step_id, output in outputs.items():
            for citation in output.citations:
                checks.append(self._check(step_id, citation.source, citation.location, sources))
        return VerificationReport(ok=all(c.ok for c in checks), checks=checks)

    @staticmethod
    def _check(
        step_id: str, source: str, location: str, sources: dict[str, dict[str, Any]]
    ) -> CitationCheck:
        if source not in sources:
            return CitationCheck(step_id, source, location, False, "unknown source")
        try:
            key, value = parse_location(location)
        except ValueError as exc:
            return CitationCheck(step_id, source, location, False, f"bad location: {exc}")

        entry = sources[source]
        if key == "page":
            pages = entry.get("pages", set())
            if value in pages:
                return CitationCheck(step_id, source, location, True)
            return CitationCheck(step_id, source, location, False, "page not in source")
        if key == "row":
            row_count = entry.get("row_count")
            if isinstance(row_count, int) and 0 <= value < row_count:
                return CitationCheck(step_id, source, location, True)
            return CitationCheck(step_id, source, location, False, "row out of range")
        return CitationCheck(step_id, source, location, False, f"unsupported location key: {key}")
