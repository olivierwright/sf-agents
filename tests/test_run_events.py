"""Tests for the on_event callback emitted by Executor.

Fully offline: stub primitives are built in-memory; no PDFs, no Bedrock, no
filesystem (except tmp_path for audit dirs where needed).
"""

from __future__ import annotations

import pytest

from sf_agents.config import Config
from sf_agents.orchestrator import Executor
from sf_agents.orchestrator.events import EventType, RunEvent
from sf_agents.orchestrator.planner import Plan, Step
from sf_agents.orchestrator.registry import Registry
from sf_agents.primitives.base import BasePrimitive, PrimitiveInput, PrimitiveOutput


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_factory(prim_name: str, *, confidence: float = 1.0):
    """Return a registry-compatible factory for a minimal stub primitive."""

    class _Prim(BasePrimitive):
        name = prim_name
        version = "0.0.1"
        capability = "stub primitive"
        inputs: dict[str, str] = {}
        outputs: dict[str, str] = {}

        def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
            return PrimitiveOutput(
                payload={"result": prim_name},
                confidence=confidence,
            )

    return lambda hook: _Prim(audit_hook=hook)


def _build_registry(*entries: tuple[str, float]) -> Registry:
    reg = Registry()
    for name, conf in entries:
        reg.register(_make_factory(name, confidence=conf))
    return reg


def _build_plan(*steps: tuple[str, str, dict]) -> Plan:
    """Build a Plan from (step_id, primitive_name, args) tuples."""
    return Plan(
        steps=[Step(sid, prim, args) for sid, prim, args in steps],
        explanation="test plan",
        source="fallback",
    )


def _cfg(tmp_path, *, floor: float = 0.70) -> Config:
    return Config(
        data_dir=tmp_path / "data",
        audit_dir=tmp_path / "audit",
        confidence_floor=floor,
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_event_types_and_order(tmp_path):
    """Events are emitted in the correct lifecycle order."""
    registry = _build_registry(("stub.a", 1.0), ("stub.b", 1.0))
    plan = _build_plan(
        ("s1", "stub.a", {}),
        ("s2", "stub.b", {"x": {"$from": "s1", "path": "payload.result"}}),
    )

    events: list[RunEvent] = []
    Executor(registry, config=_cfg(tmp_path), on_event=events.append).run(
        plan, run_id="testrun"
    )

    types = [e.type for e in events]
    assert types[0] == EventType.RUN_STARTED
    assert types[1] == EventType.PLAN_READY
    assert types[-1] == EventType.RUN_FINISHED

    # Every STEP_STARTED must be immediately followed by STEP_FINISHED
    step_types = [
        e.type
        for e in events
        if e.type in {EventType.STEP_STARTED, EventType.STEP_FINISHED}
    ]
    assert step_types == [
        EventType.STEP_STARTED,
        EventType.STEP_FINISHED,
        EventType.STEP_STARTED,
        EventType.STEP_FINISHED,
    ]


def test_plan_ready_payload_matches_plan(tmp_path):
    """plan_ready payload reflects the plan's steps, explanation and source."""
    registry = _build_registry(("stub.x", 1.0))
    plan = Plan(
        steps=[Step("only", "stub.x", {})],
        explanation="my explanation",
        source="fallback",
    )

    events: list[RunEvent] = []
    Executor(registry, config=_cfg(tmp_path), on_event=events.append).run(
        plan, run_id="r1"
    )

    pr = next(e for e in events if e.type == EventType.PLAN_READY)
    assert pr.payload["step_count"] == 1
    assert pr.payload["explanation"] == "my explanation"
    assert pr.payload["source"] == "fallback"
    assert pr.payload["steps"][0]["step_id"] == "only"
    assert pr.payload["steps"][0]["primitive"] == "stub.x"


def test_step_finished_payload_has_audit_fields(tmp_path):
    """step_finished payload includes confidence and duration_ms from the audit record."""
    registry = _build_registry(("stub.p", 0.9))
    plan = _build_plan(("s1", "stub.p", {}))

    events: list[RunEvent] = []
    Executor(registry, config=_cfg(tmp_path), on_event=events.append).run(
        plan, run_id="r2"
    )

    sf = next(e for e in events if e.type == EventType.STEP_FINISHED)
    assert sf.payload["step_id"] == "s1"
    assert sf.payload["primitive"] == "stub.p"
    assert sf.payload["confidence"] == pytest.approx(0.9)
    assert sf.payload["duration_ms"] is not None
    assert sf.payload["duration_ms"] >= 0.0
    assert isinstance(sf.payload["citations"], list)
    assert isinstance(sf.payload["issues"], list)


def test_step_count_matches_step_finished_events(tmp_path):
    """plan_ready.step_count equals the number of STEP_FINISHED events."""
    registry = _build_registry(("stub.a", 1.0), ("stub.b", 1.0), ("stub.c", 1.0))
    plan = _build_plan(
        ("s1", "stub.a", {}),
        ("s2", "stub.b", {}),
        ("s3", "stub.c", {}),
    )

    events: list[RunEvent] = []
    Executor(registry, config=_cfg(tmp_path), on_event=events.append).run(
        plan, run_id="r_count"
    )

    pr = next(e for e in events if e.type == EventType.PLAN_READY)
    finished = [e for e in events if e.type == EventType.STEP_FINISHED]
    assert pr.payload["step_count"] == len(finished)


def test_human_review_emitted_when_confidence_below_floor(tmp_path):
    """HUMAN_REVIEW_REQ is emitted when a step's confidence < floor."""
    registry = _build_registry(("stub.low", 0.50))
    plan = _build_plan(("low_s", "stub.low", {}))

    events: list[RunEvent] = []
    Executor(registry, config=_cfg(tmp_path, floor=0.80), on_event=events.append).run(
        plan, run_id="r3"
    )

    types = [e.type for e in events]
    assert EventType.HUMAN_REVIEW_REQ in types

    hr = next(e for e in events if e.type == EventType.HUMAN_REVIEW_REQ)
    assert hr.payload["step_id"] == "low_s"
    assert hr.payload["confidence"] == pytest.approx(0.50)

    # HUMAN_REVIEW_REQ must come after STEP_FINISHED for the same step
    idx_sf = next(
        i
        for i, e in enumerate(events)
        if e.type == EventType.STEP_FINISHED and e.payload["step_id"] == "low_s"
    )
    idx_hr = next(
        i for i, e in enumerate(events) if e.type == EventType.HUMAN_REVIEW_REQ
    )
    assert idx_hr > idx_sf


def test_run_error_emitted_on_step_failure(tmp_path):
    """RUN_ERROR is emitted when a step raises; the original exception still propagates."""

    class _FailPrim(BasePrimitive):
        name = "stub.fail"
        version = "0.0.1"
        capability = "always fails"
        inputs: dict[str, str] = {}
        outputs: dict[str, str] = {}

        def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
            raise RuntimeError("boom")

    registry = Registry()
    registry.register(lambda hook: _FailPrim(audit_hook=hook))
    plan = _build_plan(("s_fail", "stub.fail", {}))

    events: list[RunEvent] = []
    executor = Executor(registry, config=_cfg(tmp_path), on_event=events.append)
    with pytest.raises(RuntimeError, match="boom"):
        executor.run(plan, run_id="r4")

    types = [e.type for e in events]
    assert EventType.RUN_ERROR in types
    assert EventType.RUN_FINISHED not in types

    err = next(e for e in events if e.type == EventType.RUN_ERROR)
    assert "boom" in err.payload["message"]
    assert err.payload["step_id"] == "s_fail"


def test_no_callback_is_backward_compatible(tmp_path):
    """Executor without on_event runs identically to before the change."""
    registry = _build_registry(("stub.noop", 1.0))
    plan = _build_plan(("s1", "stub.noop", {}))

    # Must not raise; must return a valid ExecutionResult
    result = Executor(registry, config=_cfg(tmp_path)).run(plan, run_id="noevent")
    assert result.final_step_id == "s1"
    assert result.run_id == "noevent"


def test_events_have_timestamps(tmp_path):
    """Every emitted event carries a non-empty ISO-8601 timestamp."""
    registry = _build_registry(("stub.t", 1.0))
    plan = _build_plan(("s1", "stub.t", {}))

    events: list[RunEvent] = []
    Executor(registry, config=_cfg(tmp_path), on_event=events.append).run(
        plan, run_id="ts_run"
    )

    for ev in events:
        assert ev.timestamp, f"Missing timestamp on {ev.type}"
        # ISO-8601 UTC ends with +00:00 or Z
        assert "T" in ev.timestamp
