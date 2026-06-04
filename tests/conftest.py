"""Shared pytest fixtures. Everything here keeps the suite fully offline.

No fixture touches AWS/Bedrock or the network. LLM-backed primitives receive the
``mock_llm`` callable so the whole stack runs deterministically.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def mock_llm():
    """A deterministic JSON-LLM stand-in.

    It inspects the prompt and returns plausible structured output for the two
    LLM-backed primitives (definition extraction and comparison). It deliberately
    does NOT return a valid plan object, so the planner always falls back to its
    deterministic plan under test.
    """

    def llm(prompt: str, system: str | None = None, **_: object):
        sys_low = (system or "").lower()
        prompt_low = prompt.lower()

        # Waterfall extraction — identified by system prompt content
        if "waterfall mechanics" in sys_low:
            return [
                {"rank": 1, "beneficiary": "Senior fees",
                 "amount_basis": "capped at 0.02% p.a. of note balance",
                 "conditions": "none", "page": 5,
                 "excerpt": "First, senior fees capped at 0.02%"},
                {"rank": 2, "beneficiary": "Class A interest",
                 "amount_basis": "scheduled interest amount",
                 "conditions": "none", "page": 5,
                 "excerpt": "Second, Class A interest"},
                {"rank": 3, "beneficiary": "Principal deficiency ledger cure",
                 "amount_basis": "PDL balance", "conditions": "PDL debit > 0",
                 "page": 6, "excerpt": "Third, cure of PDL debit"},
            ]

        # Covenant extraction — identified by system prompt content
        if "covenant mechanics" in sys_low:
            return [
                {"type": "OC ratio test", "threshold": "105%", "test_frequency": "monthly",
                 "breach_consequence": "PDL cure required", "page": 8,
                 "excerpt": "OC Ratio Test: must be at least 105%"},
                {"type": "PDL trigger", "threshold": "2%", "test_frequency": "monthly",
                 "breach_consequence": "sequential payment mode", "page": 9,
                 "excerpt": "PDL Trigger: arrears exceed 2% of collateral balance"},
            ]

        # Cashflow anomaly narration — identified by system prompt content
        if "cashflow analyst" in sys_low:
            return [
                {"period": "2026-01", "rationale": "Seasonal prepayment spike in January."},
            ]

        # Rating action parsing — identified by system prompt content
        if "rating agency action" in sys_low or "credit analyst" in sys_low:
            return [
                {"action_type": "affirm", "tranche": "Class A",
                 "old_rating": "AAA", "new_rating": "AAA",
                 "rationale": "stable collateral performance and adequate credit enhancement",
                 "page": 2, "excerpt": "Class A notes affirmed at AAA"},
            ]

        # Definition comparison — identified by prompt start
        if prompt_low.startswith("compare how"):
            return [
                {"term": "arrears", "materiality": "moderate",
                 "rationale": "Bucket boundaries differ between the two sources."},
                {"term": "default", "materiality": "material",
                 "rationale": "Different default triggers (90-day CRR vs servicer flag)."},
                {"term": "cure", "materiality": "moderate",
                 "rationale": "Cure is formal in one source, operational in the other."},
            ]

        # Default: definition extraction
        return [
            {"term": "arrears", "definition": "amounts past their due date",
             "page": 1, "excerpt": "Arrears"},
            {"term": "default", "definition": "a loan classified as defaulted",
             "page": 1, "excerpt": "Default"},
            {"term": "cure", "definition": "return to performing status",
             "page": 1, "excerpt": "Cure"},
        ]

    return llm
