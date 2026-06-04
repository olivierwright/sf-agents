"""Orchestration strategy layer.

A strategy wraps :class:`Planner` with a specific prompt-augmentation or
post-processing policy. All three strategies use the same DAG executor — the
difference is how the question is framed (Thorough, Minimal) or how the
resulting plan is annotated (ParallelFirst).

Usage::

    from sf_agents.orchestrator.strategies import build_strategy

    strategy = build_strategy("minimal")
    plan = strategy.plan(question, registry, context=ctx, fallback=fb)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .planner import Plan, Planner, _iter_refs
from .registry import Registry

JsonLLM = Callable[..., Any]


class BaseStrategy:
    """Wraps :class:`Planner` with a strategy-specific policy."""

    strategy_id: str = "base"

    def __init__(self, llm: Optional[JsonLLM] = None) -> None:
        self._planner = Planner(llm=llm)

    def plan(
        self,
        question: str,
        registry: Registry,
        *,
        context: Optional[dict] = None,
        fallback: Optional[Plan] = None,
    ) -> Plan:
        raise NotImplementedError


class ThoroughStrategy(BaseStrategy):
    """LLM selects all relevant primitives for maximum coverage (default)."""

    strategy_id = "thorough"

    def plan(self, question, registry, *, context=None, fallback=None) -> Plan:
        return self._planner.plan(question, registry, context=context, fallback=fallback)


class MinimalStrategy(BaseStrategy):
    """LLM given a cost-optimisation constraint: fewest steps that still verify."""

    strategy_id = "minimal"

    _CONSTRAINT = (
        "\n\nPLANNING CONSTRAINT: Produce the MINIMUM number of steps that still "
        "produce a cited, verified answer. Prefer primitives that combine multiple "
        "functions. Omit any step whose output is not directly needed by a later step "
        "or the final answer. Do not include validation steps unless the question "
        "explicitly asks about data quality."
    )

    def plan(self, question, registry, *, context=None, fallback=None) -> Plan:
        return self._planner.plan(
            question + self._CONSTRAINT, registry, context=context, fallback=fallback
        )


class ParallelFirstStrategy(BaseStrategy):
    """Same plan as Thorough, annotated with topological wave groupings.

    Steps are sorted by dependency depth and the plan explanation is augmented
    with wave metadata so the UI can show which steps could run in parallel.
    The executor still runs serially — true parallelism is a future sprint.
    """

    strategy_id = "parallel_first"

    def plan(self, question, registry, *, context=None, fallback=None) -> Plan:
        base_plan = self._planner.plan(question, registry, context=context, fallback=fallback)
        return self._annotate_waves(base_plan)

    @staticmethod
    def _annotate_waves(plan: Plan) -> Plan:
        by_id = {s.step_id: s for s in plan.steps}
        deps = {
            s.step_id: set(s.depends_on) | set(_iter_refs(s.args))
            for s in plan.steps
        }
        depth: dict[str, int] = {}

        def _depth(sid: str) -> int:
            if sid in depth:
                return depth[sid]
            depth[sid] = 0 if not deps[sid] else 1 + max(_depth(d) for d in deps[sid])
            return depth[sid]

        for sid in by_id:
            _depth(sid)

        groups: dict[int, list[str]] = {}
        for sid, d in depth.items():
            groups.setdefault(d, []).append(sid)

        wave_desc = "; ".join(
            f"wave {d}: [{', '.join(sorted(ids))}]" for d, ids in sorted(groups.items())
        )
        sorted_steps = sorted(plan.steps, key=lambda s: depth[s.step_id])
        new_explanation = f"{plan.explanation} | Parallel waves — {wave_desc}"
        return Plan(steps=sorted_steps, explanation=new_explanation, source=plan.source)


_STRATEGY_MAP: dict[str, type[BaseStrategy]] = {
    "thorough": ThoroughStrategy,
    "minimal": MinimalStrategy,
    "parallel_first": ParallelFirstStrategy,
}


def build_strategy(strategy_id: str, llm: Optional[JsonLLM] = None) -> BaseStrategy:
    """Construct a strategy instance by id.

    Args:
        strategy_id: One of ``"thorough"``, ``"minimal"``, ``"parallel_first"``.
        llm: Optional JSON-LLM callable (defaults to Bedrock inside Planner).

    Raises:
        ValueError: If ``strategy_id`` is not recognised.
    """
    cls = _STRATEGY_MAP.get(strategy_id)
    if cls is None:
        raise ValueError(
            f"Unknown strategy: {strategy_id!r}. Valid: {sorted(_STRATEGY_MAP)}"
        )
    return cls(llm=llm)
