"""Test run-event emission follows strict lifecycle sequence.

Uses the loan-tape connector (only needs a CSV) so no pypdf dependency.
Asserts:
  1. Strict sequence: run_started → plan_ready → N×(step_started → step_finished) → run_finished
  2. step_finished includes confidence and duration_ms
  3. plan_ready.step_count == number of step_finished events
  4. Forced low confidence → human_review_req appears in sequence
"""

from __future__ import annotations

import pytest

from sf_agents.config import Config
from sf_agents.governance.audit_logger import open_logger
from sf_agents.orchestrator.events import EventType, RunEvent
from sf_agents.orchestrator.executor import Executor
from sf_agents.orchestrator.planner import Plan, Step
from sf_agents.orchestrator.registry import build_default_registry


FAKE_CSV = "loan_id,epc_label,current_balance\n1,A,100000\n2,B,200000\n"


@pytest.fixture
def events_log():
    """Mutable list to collect emitted RunEvents."""
    return []


@pytest.fixture
def recorder(events_log):
    """An on_event callback that appends to events_log."""

    def _record(ev: RunEvent) -> None:
        events_log.append(ev)

    return _record


@pytest.fixture
def simple_plan(tmp_path, mock_llm) -> tuple[Plan, "Registry", Config]:
    """A 2-step plan using only loan tape connectors (no PDF, no LLM)."""
    cfg = Config(
        data_dir=tmp_path / "data",
        audit_dir=tmp_path / "audit",
        confidence_floor=0.70,
    )
    data_dir = cfg.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    tape_path = data_dir / "tape.csv"
    tape_path.write_text(FAKE_CSV)
    tape2_path = data_dir / "tape2.csv"
    tape2_path.write_text(FAKE_CSV)

    registry = build_default_registry(llm=mock_llm)

    plan = Plan(
        steps=[
            Step(
                step_id="tape_load",
                primitive="connector.loan_tape",
                args={"path": str(tape_path)},
            ),
            Step(
                step_id="tape_load_2",
                primitive="connector.loan_tape",
                args={"path": str(tape2_path)},
                depends_on=["tape_load"],
            ),
        ],
        explanation="Load two tapes sequentially",
        source="fallback",
    )

    return plan, registry, cfg


def test_event_sequence_strict(simple_plan, recorder, events_log):
    """Events follow strict lifecycle order."""
    plan, registry, cfg = simple_plan
    audit = open_logger(cfg.audit_dir, "test-run-001")
    executor = Executor(registry, config=cfg, audit_logger=audit, on_event=recorder)

    executor.run(plan, run_id="test-run-001")

    types = [ev.type for ev in events_log]

    # Must start with run_started
    assert types[0] == EventType.RUN_STARTED

    # Then plan_ready
    assert types[1] == EventType.PLAN_READY

    # Then pairs of step_started + step_finished
    step_events = types[2:]
    # run_finished is last
    assert step_events[-1] == EventType.RUN_FINISHED

    # Between plan_ready and run_finished: only step_started/step_finished pairs
    middle = step_events[:-1]
    for i in range(0, len(middle), 2):
        assert middle[i] == EventType.STEP_STARTED
        assert middle[i + 1] == EventType.STEP_FINISHED


def test_plan_ready_step_count_matches(simple_plan, recorder, events_log):
    """plan_ready.step_count == number of step_finished events."""
    plan, registry, cfg = simple_plan
    audit = open_logger(cfg.audit_dir, "test-run-002")
    executor = Executor(registry, config=cfg, audit_logger=audit, on_event=recorder)

    executor.run(plan, run_id="test-run-002")

    plan_ready = next(e for e in events_log if e.type == EventType.PLAN_READY)
    step_finished_count = sum(
        1 for e in events_log if e.type == EventType.STEP_FINISHED
    )
    assert plan_ready.payload["step_count"] == step_finished_count


def test_step_finished_has_audit_keys(simple_plan, recorder, events_log):
    """step_finished payload includes confidence and duration_ms."""
    plan, registry, cfg = simple_plan
    audit = open_logger(cfg.audit_dir, "test-run-003")
    executor = Executor(registry, config=cfg, audit_logger=audit, on_event=recorder)

    executor.run(plan, run_id="test-run-003")

    step_finished_events = [e for e in events_log if e.type == EventType.STEP_FINISHED]
    assert len(step_finished_events) > 0
    for ev in step_finished_events:
        assert "confidence" in ev.payload
        assert "duration_ms" in ev.payload
        assert "step_id" in ev.payload
        assert "primitive" in ev.payload


def test_low_confidence_triggers_human_review(tmp_path, events_log, recorder, mock_llm):
    """When confidence_floor is impossibly high, human_review_req fires."""
    cfg = Config(
        data_dir=tmp_path / "data",
        audit_dir=tmp_path / "audit",
        confidence_floor=1.01,  # above max possible 1.0 — everything triggers review
    )
    data_dir = cfg.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    tape_path = data_dir / "tape.csv"
    tape_path.write_text(FAKE_CSV)

    registry = build_default_registry(llm=mock_llm)
    plan = Plan(
        steps=[
            Step(
                step_id="tape_load",
                primitive="connector.loan_tape",
                args={"path": str(tape_path)},
            ),
        ],
        explanation="Simple plan for review trigger test",
        source="fallback",
    )

    audit = open_logger(cfg.audit_dir, "test-run-review")
    executor = Executor(registry, config=cfg, audit_logger=audit, on_event=recorder)
    executor.run(plan, run_id="test-run-review")

    types = [ev.type for ev in events_log]
    # Should contain HUMAN_REVIEW_REQ
    assert EventType.HUMAN_REVIEW_REQ in types
    # And it must come after the corresponding step_finished
    review_idx = types.index(EventType.HUMAN_REVIEW_REQ)
    assert types[review_idx - 1] == EventType.STEP_FINISHED
