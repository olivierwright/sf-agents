"""Helpers for building and parsing :class:`Citation` locations.

A citation ``location`` is a compact ``key=value`` string (e.g. ``"page=42"`` or
``"row=17"``). Keeping a single canonical form lets the verifier mechanically
check that the referenced page/row truly exists in the source chunk.
"""

from __future__ import annotations

from typing import Iterable

from ..primitives.base import Citation


def page_location(page: int) -> str:
    """Canonical location string for a 1-based PDF page."""
    return f"page={int(page)}"


def row_location(row: int) -> str:
    """Canonical location string for a 0-based tabular row index."""
    return f"row={int(row)}"


def parse_location(location: str) -> tuple[str, int]:
    """Parse a ``key=value`` location into ``(key, int_value)``.

    Raises:
        ValueError: If the location is not a single ``key=<int>`` pair.
    """
    if "=" not in location:
        raise ValueError(f"Malformed citation location (expected key=value): {location!r}")
    key, _, raw = location.partition("=")
    key = key.strip()
    try:
        value = int(raw.strip())
    except ValueError as exc:  # noqa: PERF203 - clarity over micro-perf
        raise ValueError(f"Non-integer citation location value: {location!r}") from exc
    return key, value


def citations_to_dicts(citations: Iterable[Citation]) -> list[dict[str, str]]:
    """Serialise an iterable of citations to plain dicts."""
    return [c.as_dict() for c in citations]
