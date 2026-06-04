"""Tests for the registry and the default catalogue."""

from __future__ import annotations

import pytest

from sf_agents.orchestrator.registry import Registry, build_default_registry
from sf_agents.primitives.base import BasePrimitive, PrimitiveInput, PrimitiveOutput

EXPECTED = {
    # Connectors
    "connector.prospectus",
    "connector.investor_report",
    "connector.pdf_document",
    "connector.loan_tape",
    "connector.remittance_file",
    # Validators
    "validator.esma_schema",
    # Extractors
    "extractor.definitions",
    "extractor.waterfall",
    "extractor.covenants",
    # Analyzers
    "analyzer.definition_comparator",
    "analyzer.claim_vs_collateral",
    "analyzer.cashflow_anomaly",
    "analyzer.covenant_compliance",
    "analyzer.rating_action",
}


class _Dummy(BasePrimitive):
    name = "test.dummy"
    version = "0.1.0"
    capability = "dummy"

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        return PrimitiveOutput(payload={})


def test_default_registry_contains_all_primitives():
    reg = build_default_registry()
    assert set(reg.names()) == EXPECTED


def test_describe_returns_capability_strings():
    reg = build_default_registry()
    described = {d["name"]: d for d in reg.describe()}
    assert described["analyzer.definition_comparator"]["capability"]
    assert all({"name", "version", "capability"} <= set(d) for d in reg.describe())


def test_build_returns_instance_and_unknown_raises():
    reg = build_default_registry()
    prim = reg.build("validator.esma_schema")
    assert prim.name == "validator.esma_schema"
    with pytest.raises(KeyError):
        reg.build("nope")


def test_duplicate_registration_raises():
    reg = Registry()
    reg.register(lambda hook: _Dummy(audit_hook=hook))
    with pytest.raises(ValueError):
        reg.register(lambda hook: _Dummy(audit_hook=hook))


def test_llm_injection_reaches_llm_primitives():
    sentinel = object()
    reg = build_default_registry(llm=lambda *a, **k: sentinel)
    extractor = reg.build("extractor.definitions")
    # The injected llm should be the one stored on the primitive.
    assert extractor._llm("x") is sentinel
