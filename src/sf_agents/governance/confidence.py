"""Confidence policy: aggregation and the human-review floor check."""

from __future__ import annotations

from typing import Iterable

from ..config import get_config


def is_below_floor(confidence: float, floor: float | None = None) -> bool:
    """Return True if ``confidence`` is strictly below the configured floor.

    Args:
        confidence: The value to test, in ``[0, 1]``.
        floor: Optional explicit floor; defaults to the configured value.
    """
    if floor is None:
        floor = get_config().confidence_floor
    return float(confidence) < float(floor)


def aggregate_confidence(values: Iterable[float]) -> float:
    """Combine step confidences into an overall run confidence.

    Uses the minimum: a chain is only as trustworthy as its weakest link.
    Returns ``1.0`` for an empty sequence (nothing uncertain happened).
    """
    vals = [float(v) for v in values]
    return min(vals) if vals else 1.0
