"""Run the impact-mapping recipe on the Green Lion 2026-1 sample data.

Usage:
    # Real run (requires AWS Bedrock env vars; see README / .env.example):
    python examples/02_impact_mapping.py

    # Fully offline run with the bundled deterministic mock LLM (no Bedrock):
    python examples/02_impact_mapping.py --offline

The script prints the live plan, the cited answer (each verdict grounded in both
a document page and specific loan-tape rows), the verification result and the
path to the append-only audit log.
"""

from __future__ import annotations

import argparse
import json
import sys

from sf_agents.recipes.impact_mapping import run_impact_mapping


def _offline_llm():
    """A deterministic stand-in LLM so the demo runs without Bedrock.

    It pattern-matches the prompt prefix to return plausible JSON for the
    green-claim extraction and the claim-vs-collateral assessment. It does NOT
    return a valid plan object, so the planner falls back to the deterministic
    plan.
    """

    def llm(prompt: str, system: str | None = None, **_: object):
        low = prompt.lower()
        if low.startswith("assess whether each green claim"):
            return [
                {"claim": "EPC label", "verdict": "supported",
                 "rationale": "The tape is dominated by A/A+ EPC labels, matching the green-label claim."},
                {"claim": "primary energy demand", "verdict": "partially supported",
                 "rationale": "Mean primary energy demand is low but a tail of higher-demand loans remains."},
                {"claim": "construction deposit", "verdict": "not supported",
                 "rationale": "Almost no loans carry a construction-deposit flag in the tape."},
                {"claim": "energy efficiency", "verdict": "supported",
                 "rationale": "Energy-efficiency fields are populated and skew efficient."},
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run with a deterministic mock LLM instead of AWS Bedrock.",
    )
    args = parser.parse_args(argv)

    llm = _offline_llm() if args.offline else None
    result = run_impact_mapping(llm=llm, use_planner=not args.offline)

    print("=" * 70)
    print(f"run_id: {result['run_id']}")
    print(f"plan source: {result['plan']['source']}")
    print("-" * 70)
    print("PLAN")
    print(json.dumps(result["plan"], indent=2))
    print("-" * 70)
    print(result["answer"])
    print("-" * 70)
    print(f"citations verified: {result['verification']['ok']} "
          f"({result['verification']['total']} checked)")
    print(f"audit log: {result['audit_path']}")
    if result["review_queue"]:
        print(f"human review queue: {len(result['review_queue'])} item(s)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
