"""End-to-end test of the impact-mapping recipe + the claim_vs_collateral analyzer.

Runs the full stack on the REAL Green Lion 2026-1 PDFs and CSV using a
deterministic mock LLM (no Bedrock/network). Asserts that every citation in the
result is dual-grounded -- a real document page AND a real loan-tape row -- and
verifies against the real sources.
"""

from __future__ import annotations

import json

import pytest

from sf_agents.primitives.analyzers.claim_vs_collateral import ClaimVsCollateral
from sf_agents.primitives.base import PrimitiveInput
from sf_agents.primitives.connectors.loan_tape import LoanTapeConnector
from sf_agents.recipes.impact_mapping import run_impact_mapping


@pytest.fixture
def impact_llm():
    """Deterministic LLM: green claims on extraction, verdicts on assessment."""

    def llm(prompt: str, system: str | None = None, **_: object):
        low = prompt.lower()
        if low.startswith("assess whether each green claim"):
            return [
                {"claim": "EPC label", "verdict": "supported",
                 "rationale": "The tape skews to A/A+ EPC labels."},
                {"claim": "primary energy demand", "verdict": "partially supported",
                 "rationale": "Mean demand is low but a higher-demand tail remains."},
                {"claim": "construction deposit", "verdict": "not supported",
                 "rationale": "Almost no loans carry a construction-deposit flag."},
                {"claim": "energy efficiency", "verdict": "supported",
                 "rationale": "Energy-efficiency fields skew efficient."},
            ]
        # Green-claim extraction prompts start with "Document: ".
        return [
            {"term": "EPC label", "definition": "the portfolio targets high EPC labels",
             "page": 1, "excerpt": "EPC"},
            {"term": "primary energy demand", "definition": "low primary energy demand per m2",
             "page": 1, "excerpt": "energy"},
            {"term": "construction deposit", "definition": "loans may include a construction deposit",
             "page": 1, "excerpt": "construction"},
            {"term": "energy efficiency", "definition": "the pool is energy efficient",
             "page": 1, "excerpt": "energy"},
        ]

    return llm


def test_recipe_runs_and_citations_dual_ground(impact_llm, tmp_path, monkeypatch):
    monkeypatch.setenv("SF_AGENTS_AUDIT_DIR", str(tmp_path / "audit"))
    from sf_agents import config as cfg_mod
    cfg_mod.get_config.cache_clear()

    result = run_impact_mapping(llm=impact_llm, use_planner=False, run_id="impactrun")

    # Verification must pass: no hallucinated citations.
    assert result["verification"]["ok"] is True, result["verification"]["failures"]
    assert result["verification"]["total"] > 0

    # Citations must resolve on BOTH axes: at least one page and one row check.
    locations = [c["location"] for c in result["verification"]["checks"]]
    assert any(loc.startswith("page=") for loc in locations)
    assert any(loc.startswith("row=") for loc in locations)

    # Assessments came from all three claim documents and carry valid verdicts.
    assert result["assessments"], "expected at least one assessment"
    sources = {a["claim_source"] for a in result["assessments"]}
    assert len(sources) == 3  # prospectus, spo, cfp
    vocab = {"supported", "partially supported", "not supported", "not verifiable from data"}
    for a in result["assessments"]:
        assert a["verdict"] in vocab
        # Each assessment is itself dual-grounded.
        assert isinstance(a["claim_page"], int)
        assert a["tape_columns"]
        assert a["tape_rows"]

    # Audit log: one record per plan step.
    audit_path = result["audit_path"]
    lines = [l for l in open(audit_path, encoding="utf-8").read().splitlines() if l.strip()]
    assert len(lines) == len(result["plan"]["steps"])
    for line in lines:
        rec = json.loads(line)
        assert rec["run_id"] == "impactrun"

    cfg_mod.get_config.cache_clear()


def test_analyzer_grounds_against_real_tape_columns(impact_llm):
    """The analyzer computes real tape figures and dual-grounds its citations."""
    from sf_agents.config import get_config

    cfg = get_config()
    tape_path = str(cfg.deal_file("green_lion_2026_1_synthetic_loan_tape.csv"))

    tape = LoanTapeConnector().run(PrimitiveInput(args={"path": tape_path, "max_rows": 100}))
    columns = tape.payload["columns"]
    rows = tape.payload["rows"]
    tape_doc = tape.payload["document"]

    # The known green fields really are present in the tape.
    for field in ("epc_label", "primary_energy_demand_kwh_m2", "construction_deposit_flag"):
        assert field in columns

    claims = [
        {"term": "EPC label", "definition": "high EPC labels", "page": 3, "excerpt": "EPC"},
        {"term": "primary energy demand", "definition": "low primary energy demand", "page": 4, "excerpt": "energy"},
        {"term": "construction deposit", "definition": "construction deposit loans", "page": 5, "excerpt": "deposit"},
    ]
    out = ClaimVsCollateral(llm=impact_llm).run(
        PrimitiveInput(
            args={
                "claims": claims,
                "claim_source": "green-lion-2026-1-prospectus.pdf",
                "columns": columns,
                "rows": rows,
                "tape_document": tape_doc,
            }
        )
    )

    assessments = out.payload["assessments"]
    assert len(assessments) == 3

    # Tape facts were computed deterministically from the real rows.
    epc = next(a for a in assessments if a["claim"] == "EPC label")
    assert "epc_label" in epc["tape_columns"]
    assert epc["tape_facts"]["epc_label"]["distribution"]  # real label distribution

    ped = next(a for a in assessments if a["claim"] == "primary energy demand")
    facts = ped["tape_facts"]["primary_energy_demand_kwh_m2"]
    assert facts["n"] > 0 and "mean" in facts

    # Citations are dual-grounded: a real page on the doc side, real rows on the
    # tape side, and every cited row index is in range.
    page_cites = [c for c in out.citations if c.location.startswith("page=")]
    row_cites = [c for c in out.citations if c.location.startswith("row=")]
    assert page_cites and row_cites
    for c in row_cites:
        idx = int(c.location.split("=", 1)[1])
        assert 0 <= idx < len(rows)
