"""Use case catalogue — discovery templates for structured-finance analysis.

Each entry is a lightweight template with an example question and suggested
primitives. Clicking a use case in the UI pre-fills the question field.
Execution always goes through the dynamic orchestrator — not a hardcoded path.
"""

from __future__ import annotations

USE_CASES: list[dict] = [
    {
        "id": "definition_transparency",
        "label": "Definition Transparency",
        "category": "documentation",
        "example_question": (
            "How does the prospectus formally define arrears, default and cure, "
            "and where does the investor report diverge materially?"
        ),
        "suggested_primitives": [
            "connector.prospectus",
            "connector.investor_report",
            "connector.loan_tape",
            "validator.esma_schema",
            "extractor.definitions",
            "analyzer.definition_comparator",
        ],
        "description": (
            "Compare how key performance terms (arrears, default, cure) are defined "
            "in the prospectus versus how the investor report actually applies them. "
            "Surfaces material divergences with page-level citations from both documents."
        ),
        "terms": ["arrears", "default", "cure"],
    },
    {
        "id": "impact_mapping",
        "label": "Impact Mapping",
        "category": "esg",
        "example_question": (
            "Do the green claims in the prospectus and ISS second-party opinion "
            "hold up against the loan tape, and are the CFP impact figures consistent?"
        ),
        "suggested_primitives": [
            "connector.pdf_document",
            "connector.loan_tape",
            "extractor.definitions",
            "analyzer.claim_vs_collateral",
        ],
        "description": (
            "Test green/social claims from multiple deal documents against the "
            "actual loan tape. Each claim gets a verdict (supported / partially / "
            "not supported) with dual citations: document page + tape rows."
        ),
        "terms": ["EPC label", "primary energy demand", "construction deposit", "energy efficiency"],
    },
    {
        "id": "cashflow_anomaly",
        "label": "Cashflow Anomaly Detection",
        "category": "performance",
        "example_question": (
            "Are there anomalies in the period cashflows compared to what the "
            "loan tape would predict, and what explains them?"
        ),
        "suggested_primitives": [
            "connector.remittance_file",
            "connector.loan_tape",
            "analyzer.cashflow_anomaly",
        ],
        "description": (
            "Compare expected cashflows (derived from loan tape balances and rates) "
            "against actual period collections from the remittance file. Flags "
            "statistical outliers (Z-score) and generates plain-English explanations."
        ),
        "terms": ["collections", "interest", "principal", "prepayment", "arrears"],
    },
    {
        "id": "covenant_compliance",
        "label": "Covenant Compliance",
        "category": "compliance",
        "example_question": (
            "What covenants does the prospectus require, and does the current "
            "loan tape show compliance with each one?"
        ),
        "suggested_primitives": [
            "connector.prospectus",
            "connector.loan_tape",
            "extractor.covenants",
            "analyzer.covenant_compliance",
        ],
        "description": (
            "Extract covenant thresholds (PDL triggers, OC ratios, reserve fund "
            "requirements) from the prospectus and compute actual values from the "
            "loan tape. Returns a pass/fail verdict per covenant with cited evidence."
        ),
        "terms": ["PDL", "OC ratio", "overcollateralisation", "reserve fund", "trigger"],
    },
    {
        "id": "waterfall_transparency",
        "label": "Waterfall Transparency",
        "category": "structure",
        "example_question": (
            "What is the priority-of-payments waterfall in this deal, and which "
            "tranche bears the first loss?"
        ),
        "suggested_primitives": [
            "connector.prospectus",
            "extractor.waterfall",
        ],
        "description": (
            "Extract the complete priority-of-payments waterfall from the prospectus. "
            "Returns each step with rank, beneficiary, amount basis, conditions, "
            "and a verbatim page citation."
        ),
        "terms": ["waterfall", "priority of payments", "available funds", "interest proceeds"],
    },
    {
        "id": "rating_action",
        "label": "Rating Action Interpreter",
        "category": "ratings",
        "example_question": (
            "What rating actions have been taken on this deal, and how do they "
            "connect to the loan tape performance data?"
        ),
        "suggested_primitives": [
            "connector.pdf_document",
            "connector.loan_tape",
            "analyzer.rating_action",
        ],
        "description": (
            "Parse rating agency action announcements (upgrade, downgrade, watch, "
            "affirm) and map stated rationales to measurable loan tape metrics "
            "like arrears rate, default rate, and OC ratio."
        ),
        "terms": ["rating", "upgrade", "downgrade", "affirm", "watch", "tranche"],
    },
]
