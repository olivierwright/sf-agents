"""Tests for the orchestration strategy layer."""

from __future__ import annotations

import pytest

from sf_agents.orchestrator.planner import Plan, Step
from sf_agents.orchestrator.strategies import (
    MinimalStrategy,
    ParallelFirstStrategy,
    ThoroughStrategy,
    build_strategy,
)


def _make_plan(steps: list[Step], explanation: str = "test plan") -> Plan:
    return Plan(steps=steps, explanation=explanation, source="fallback")


def _linear_plan() -> Plan:
    return _make_plan([
        Step(step_id="load", primitive="connector.prospectus", args={"path": "/f.pdf"}),
        Step(step_id="extract", primitive="extractor.definitions",
             args={"pages": {"$from": "load", "path": "payload.pages"},
                   "terms": ["arrears"], "document": "f.pdf"},
             depends_on=["load"]),
    ])


def _parallel_plan() -> Plan:
    return _make_plan([
        Step(step_id="load_a", primitive="connector.prospectus", args={"path": "/a.pdf"}),
        Step(step_id="load_b", primitive="connector.investor_report", args={"path": "/b.pdf"}),
        Step(step_id="compare", primitive="analyzer.definition_comparator",
             args={"definitions_a": {"$from": "load_a", "path": "payload.document"},
                   "definitions_b": {"$from": "load_b", "path": "payload.document"},
                   "document_a": "a.pdf", "document_b": "b.pdf"},
             depends_on=["load_a", "load_b"]),
    ])


# ---------------------------------------------------------------------------
# build_strategy factory
# ---------------------------------------------------------------------------

def test_build_strategy_thorough(mock_llm):
    s = build_strategy("thorough", llm=mock_llm)
    assert isinstance(s, ThoroughStrategy)


def test_build_strategy_minimal(mock_llm):
    s = build_strategy("minimal", llm=mock_llm)
    assert isinstance(s, MinimalStrategy)


def test_build_strategy_parallel_first(mock_llm):
    s = build_strategy("parallel_first", llm=mock_llm)
    assert isinstance(s, ParallelFirstStrategy)


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="Unknown strategy"):
        build_strategy("quantum")


# ---------------------------------------------------------------------------
# MinimalStrategy augments question
# ---------------------------------------------------------------------------

def test_minimal_strategy_adds_planning_constraint(mock_llm):
    captured: list[str] = []

    def capturing_llm(prompt, **_):
        captured.append(prompt)
        return {"steps": [], "explanation": ""}

    from sf_agents.orchestrator.registry import build_default_registry
    registry = build_default_registry(llm=mock_llm)
    strategy = MinimalStrategy(llm=capturing_llm)

    try:
        strategy.plan("What are arrears?", registry, fallback=_linear_plan())
    except Exception:
        pass

    assert captured, "LLM should have been called"
    assert "PLANNING CONSTRAINT" in captured[0]


# ---------------------------------------------------------------------------
# ParallelFirstStrategy annotates waves
# ---------------------------------------------------------------------------

def test_parallel_first_annotates_waves():
    plan = _parallel_plan()
    annotated = ParallelFirstStrategy._annotate_waves(plan)

    assert "wave" in annotated.explanation.lower()
    assert "Parallel waves" in annotated.explanation


def test_parallel_first_sorts_by_depth():
    plan = _linear_plan()
    annotated = ParallelFirstStrategy._annotate_waves(plan)

    step_ids = [s.step_id for s in annotated.steps]
    assert step_ids.index("load") < step_ids.index("extract")


def test_parallel_first_groups_independent_steps():
    plan = _parallel_plan()
    annotated = ParallelFirstStrategy._annotate_waves(plan)

    # Both loaders have no deps → wave 0; compare → wave 1
    assert "wave 0" in annotated.explanation
    assert "wave 1" in annotated.explanation
    # The two loaders should both appear in wave 0
    assert "load_a" in annotated.explanation
    assert "load_b" in annotated.explanation


# ---------------------------------------------------------------------------
# Registry now has 14 primitives
# ---------------------------------------------------------------------------

def test_registry_has_all_new_primitives():
    from sf_agents.orchestrator.registry import build_default_registry
    registry = build_default_registry(llm=lambda *a, **kw: [])
    names = set(registry.names())
    expected = {
        "connector.remittance_file",
        "extractor.waterfall",
        "extractor.covenants",
        "analyzer.cashflow_anomaly",
        "analyzer.covenant_compliance",
        "analyzer.rating_action",
    }
    missing = expected - names
    assert not missing, f"Missing from registry: {missing}"
