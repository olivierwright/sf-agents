"""Planner tests: validation, cycle detection, and fallback behaviour."""

from __future__ import annotations

import pytest

from sf_agents.orchestrator.planner import Plan, PlanValidationError, Planner, Step
from sf_agents.orchestrator.registry import build_default_registry


def _simple_plan(source="fallback"):
    return Plan(
        steps=[
            Step("load", "connector.prospectus", {"path": "x.pdf"}),
            Step(
                "defs",
                "extractor.definitions",
                {
                    "pages": {"$from": "load", "path": "payload.pages"},
                    "terms": ["arrears"],
                },
            ),
        ],
        source=source,
    )


def test_validate_accepts_good_plan():
    reg = build_default_registry()
    Planner.validate(_simple_plan(), reg)  # must not raise


def test_validate_rejects_unknown_primitive():
    reg = build_default_registry()
    plan = Plan(steps=[Step("a", "does.not.exist", {})])
    with pytest.raises(PlanValidationError):
        Planner.validate(plan, reg)


def test_validate_rejects_reference_to_unknown_step():
    reg = build_default_registry()
    plan = Plan(
        steps=[
            Step("defs", "extractor.definitions",
                 {"pages": {"$from": "ghost", "path": "payload.pages"}}),
        ]
    )
    with pytest.raises(PlanValidationError):
        Planner.validate(plan, reg)


def test_cycle_is_detected():
    reg = build_default_registry()
    plan = Plan(
        steps=[
            Step("a", "connector.prospectus", {"x": {"$from": "b", "path": "p"}}),
            Step("b", "connector.prospectus", {"x": {"$from": "a", "path": "p"}}),
        ]
    )
    with pytest.raises(PlanValidationError):
        Planner.topological_order(plan)


def test_planner_falls_back_on_invalid_llm_output(mock_llm):
    reg = build_default_registry(llm=mock_llm)
    planner = Planner(llm=mock_llm)  # mock_llm never returns a valid plan object
    fallback = _simple_plan()
    plan = planner.plan("any question", reg, fallback=fallback)
    assert plan.source == "fallback"
    assert plan.steps == fallback.steps


def test_planner_uses_llm_plan_when_valid():
    def planning_llm(prompt, system=None, **_):
        return {
            "explanation": "load the prospectus",
            "steps": [{"step_id": "load", "primitive": "connector.prospectus",
                       "args": {"path": "x.pdf"}}],
        }

    reg = build_default_registry()
    planner = Planner(llm=planning_llm)
    plan = planner.plan("q", reg, fallback=_simple_plan())
    assert plan.source == "planner"
    assert plan.steps[0].primitive == "connector.prospectus"
