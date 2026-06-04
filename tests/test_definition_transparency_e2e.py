"""End-to-end test of the definition-transparency recipe.

Runs the full stack (connectors -> validator -> extractors -> comparator ->
verifier) on the REAL Green Lion 2026-1 PDFs and CSV, using the deterministic
``mock_llm`` so no Bedrock/network access is required. Asserts that every
citation in the result verifies against the real source pages/rows.
"""

from __future__ import annotations

import json

from sf_agents.recipes.definition_transparency import run_definition_transparency


def test_recipe_runs_and_citations_verify(mock_llm, tmp_path, monkeypatch):
    monkeypatch.setenv("SF_AGENTS_AUDIT_DIR", str(tmp_path / "audit"))
    # Clear cached config so the new audit dir is picked up.
    from sf_agents import config as cfg_mod
    cfg_mod.get_config.cache_clear()

    result = run_definition_transparency(
        llm=mock_llm,
        use_planner=False,
        run_id="testrun",
    )

    # Verification must pass: no hallucinated citations.
    assert result["verification"]["ok"] is True, result["verification"]["failures"]
    assert result["verification"]["total"] > 0

    # The answer covers all three terms.
    for term in ("arrears", "default", "cure"):
        assert term in result["answer"]

    # The loan tape validated against the ESMA subset.
    assert result["validation"]["ok"] is True

    # No low-confidence steps were routed to review with the deterministic mock.
    assert result["review_queue"] == []

    # The append-only audit log exists and contains one record per step.
    audit_path = result["audit_path"]
    assert audit_path is not None
    lines = [l for l in open(audit_path, encoding="utf-8").read().splitlines() if l.strip()]
    assert len(lines) == len(result["plan"]["steps"])
    # Each line is a valid audit record.
    for line in lines:
        rec = json.loads(line)
        assert rec["run_id"] == "testrun"
        assert "input_hash" in rec and "output_hash" in rec

    cfg_mod.get_config.cache_clear()


def test_recipe_comparisons_have_materiality(mock_llm, tmp_path, monkeypatch):
    monkeypatch.setenv("SF_AGENTS_AUDIT_DIR", str(tmp_path / "audit"))
    from sf_agents import config as cfg_mod
    cfg_mod.get_config.cache_clear()

    result = run_definition_transparency(llm=mock_llm, use_planner=False)
    materialities = {c["materiality"] for c in result["comparisons"]}
    assert materialities <= {"material", "moderate", "none"}
    assert len(result["comparisons"]) == 3

    cfg_mod.get_config.cache_clear()
