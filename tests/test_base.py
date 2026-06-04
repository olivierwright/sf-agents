"""Contract tests for the core primitive shapes and BasePrimitive plumbing."""

from __future__ import annotations

import pytest

from sf_agents.primitives.base import (
    AuditRecord,
    BasePrimitive,
    Citation,
    PrimitiveInput,
    PrimitiveOutput,
)


class _Echo(BasePrimitive):
    name = "test.echo"
    version = "9.9.9"
    capability = "Echo its args back as the payload."

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        return PrimitiveOutput(payload={"echo": inp.get("value")}, confidence=0.5)


def test_primitive_output_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        PrimitiveOutput(payload={}, confidence=1.5)
    with pytest.raises(ValueError):
        PrimitiveOutput(payload={}, confidence=-0.1)


def test_citation_as_dict_roundtrip():
    c = Citation(source="doc.pdf", location="page=3", excerpt="hello")
    assert c.as_dict() == {"source": "doc.pdf", "location": "page=3", "excerpt": "hello"}


def test_call_emits_audit_record_and_metadata():
    records: list[AuditRecord] = []
    prim = _Echo(audit_hook=records.append)
    out = prim(PrimitiveInput(args={"value": 42}), run_id="r1", step_id="s1")

    assert out.payload == {"echo": 42}
    assert len(records) == 1
    rec = records[0]
    assert rec.run_id == "r1" and rec.step_id == "s1"
    assert rec.primitive == "test.echo" and rec.version == "9.9.9"
    assert rec.confidence == 0.5
    assert rec.duration_ms >= 0.0
    assert out.metadata["audit"]["step_id"] == "s1"


def test_describe_exposes_capability():
    assert _Echo().describe() == {
        "name": "test.echo",
        "version": "9.9.9",
        "capability": "Echo its args back as the payload.",
        "inputs": {},
        "outputs": {},
    }
