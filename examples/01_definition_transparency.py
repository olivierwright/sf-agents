"""Run the definition-transparency recipe on the Green Lion 2026-1 sample data.

Usage:
    # Real run (requires AWS Bedrock env vars; see README / .env.example):
    python examples/01_definition_transparency.py

    # Fully offline run with the bundled deterministic mock LLM (no Bedrock):
    python examples/01_definition_transparency.py --offline

The script prints the live plan, the cited answer, the verification result and
the path to the append-only audit log.
"""

from __future__ import annotations

import argparse
import json
import sys

from sf_agents.recipes.definition_transparency import run_definition_transparency


def _offline_llm():
    """A deterministic stand-in LLM so the demo runs without Bedrock.

    It pattern-matches the prompt to return plausible JSON for both the
    definition-extraction and the comparison steps. The planner falls back to the
    deterministic plan because this mock does not emit a valid plan object.
    """

    def llm(prompt: str, system: str | None = None, **_: object):
        low = prompt.lower()
        if low.startswith("compare how"):
            return [
                {"term": "arrears", "materiality": "moderate",
                 "rationale": "Both track missed payments but bucket boundaries differ."},
                {"term": "default", "materiality": "material",
                 "rationale": "Prospectus ties default to a 90-day CRR trigger; the report uses a servicer status flag."},
                {"term": "cure", "materiality": "moderate",
                 "rationale": "Cure conditions are defined formally in the prospectus but only implied operationally in the report."},
            ]
        # Definition-extraction prompts list [PAGE n] blocks.
        return [
            {"term": "arrears", "definition": "amounts past their due date", "page": 1,
             "excerpt": "Arrears"},
            {"term": "default", "definition": "a loan classified as defaulted", "page": 1,
             "excerpt": "Default"},
            {"term": "cure", "definition": "return to performing status", "page": 1,
             "excerpt": "Cure"},
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
    result = run_definition_transparency(llm=llm, use_planner=not args.offline)

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
