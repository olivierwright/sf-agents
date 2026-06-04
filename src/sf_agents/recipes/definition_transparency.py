"""Recipe: *definition transparency* across Green Lion 2026-1 documents.

Question it answers:
    "How does the prospectus formally define key performance terms (arrears,
    default, cure), how does the ongoing investor report use those same terms,
    and where do the two diverge materially?"

This is the framework's flagship recipe. It exercises the whole stack end to end
on the real sample data:

    connector.prospectus ─┐
    connector.investor_report ─┤      extractor.definitions (x2)
    connector.loan_tape ─┘  ─►  validator.esma_schema
                                 │
                                 ▼
                    analyzer.definition_comparator ─► cited, verified answer

The planner is asked to produce this DAG live; if the LLM is unavailable or
returns an invalid plan, the deterministic fallback below runs instead and the
chosen path is logged. Every citation in the final answer is checked against the
real source pages/rows by the verifier before the answer is returned.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from ..config import Config, get_config
from ..governance.audit_logger import open_logger
from ..orchestrator.executor import Executor
from ..orchestrator.planner import Plan, Planner, Step
from ..orchestrator.registry import build_default_registry
from ..orchestrator.verifier import Verifier

DEFAULT_TERMS = ["arrears", "default", "cure"]

PROSPECTUS_FILE = "green-lion-2026-1-prospectus.pdf"
INVESTOR_REPORT_FILE = "monthly-investor-report-green-lion-2026-1-april-2026.pdf"
LOAN_TAPE_FILE = "green_lion_2026_1_synthetic_loan_tape.csv"

QUESTION = (
    "How does the prospectus define the key performance terms (arrears, default, "
    "cure), how does the monthly investor report use those same terms, and where "
    "do the two sources diverge materially?"
)


def _ref(step_id: str, path: str) -> dict[str, str]:
    """A plan reference object resolving to an upstream step's output value."""
    return {"$from": step_id, "path": path}


def build_fallback_plan(
    *,
    prospectus_path: str,
    investor_report_path: str,
    loan_tape_path: str,
    terms: list[str],
) -> Plan:
    """The deterministic, proven DAG used when the LLM planner is unavailable."""
    steps = [
        Step("prospectus_load", "connector.prospectus", {"path": prospectus_path}),
        Step("ir_load", "connector.investor_report", {"path": investor_report_path}),
        Step("tape_load", "connector.loan_tape", {"path": loan_tape_path}),
        Step(
            "tape_validate",
            "validator.esma_schema",
            {
                "columns": _ref("tape_load", "payload.columns"),
                "rows": _ref("tape_load", "payload.rows"),
                "document": _ref("tape_load", "payload.document"),
            },
        ),
        Step(
            "defs_prospectus",
            "extractor.definitions",
            {
                "pages": _ref("prospectus_load", "payload.pages"),
                "terms": list(terms),
                "document": _ref("prospectus_load", "payload.document"),
            },
        ),
        Step(
            "defs_ir",
            "extractor.definitions",
            {
                "pages": _ref("ir_load", "payload.pages"),
                "terms": list(terms),
                "document": _ref("ir_load", "payload.document"),
            },
        ),
        Step(
            "compare",
            "analyzer.definition_comparator",
            {
                "source_a": _ref("defs_prospectus", "payload.document"),
                "source_b": _ref("defs_ir", "payload.document"),
                "definitions_a": _ref("defs_prospectus", "payload.definitions"),
                "definitions_b": _ref("defs_ir", "payload.definitions"),
            },
        ),
    ]
    return Plan(
        steps=steps,
        explanation=(
            "Load the prospectus, investor report and loan tape; validate the tape "
            "against the ESMA schema; extract definitions of the requested terms "
            "from both documents; then compare them for material divergence."
        ),
        source="fallback",
    )


def run_definition_transparency(
    *,
    config: Optional[Config] = None,
    llm: Optional[Callable[..., Any]] = None,
    terms: Optional[list[str]] = None,
    run_id: Optional[str] = None,
    use_planner: bool = True,
) -> dict[str, Any]:
    """Run the recipe end to end and return a structured, cited result.

    Args:
        config: Override configuration (defaults to :func:`get_config`).
        llm: JSON-LLM callable injected into the planner and LLM primitives.
            Defaults inside each component to the real Bedrock client; pass a
            mock for offline runs/tests.
        terms: Terms to compare (defaults to arrears/default/cure).
        run_id: Stable run identifier (defaults to a uuid4 hex).
        use_planner: If False, skip the LLM planner and run the fallback DAG
            directly (useful for fully deterministic offline runs).

    Returns:
        A dict with keys: ``run_id``, ``plan`` (dict), ``answer`` (str),
        ``comparisons`` (list), ``verification`` (dict), ``review_queue`` (list),
        ``validation`` (dict) and ``audit_path`` (str).
    """
    cfg = config or get_config()
    terms = terms or list(DEFAULT_TERMS)
    run_id = run_id or uuid.uuid4().hex[:12]

    prospectus_path = str(cfg.deal_file(PROSPECTUS_FILE))
    investor_report_path = str(cfg.deal_file(INVESTOR_REPORT_FILE))
    loan_tape_path = str(cfg.deal_file(LOAN_TAPE_FILE))

    registry = build_default_registry(llm=llm)
    fallback = build_fallback_plan(
        prospectus_path=prospectus_path,
        investor_report_path=investor_report_path,
        loan_tape_path=loan_tape_path,
        terms=terms,
    )

    if use_planner:
        planner = Planner(llm=llm)
        plan = planner.plan(
            QUESTION,
            registry,
            context={
                "documents": {
                    "prospectus": prospectus_path,
                    "investor_report": investor_report_path,
                    "loan_tape": loan_tape_path,
                },
                "terms": terms,
            },
            fallback=fallback,
        )
    else:
        Planner.validate(fallback, registry)
        plan = fallback

    audit = open_logger(cfg.audit_dir, run_id)
    executor = Executor(registry, config=cfg, audit_logger=audit)
    result = executor.run(plan, run_id=run_id)

    verifier = Verifier()
    report = verifier.verify(result.outputs, result.sources)

    final = result.final_output
    comparisons = (final.payload.get("comparisons", []) if final else []) or []
    validation = (
        result.outputs["tape_validate"].payload
        if "tape_validate" in result.outputs
        else {}
    )

    return {
        "run_id": run_id,
        "plan": plan.as_dict(),
        "answer": format_answer(comparisons, report.ok),
        "comparisons": comparisons,
        "verification": report.as_dict(),
        "review_queue": result.review_queue,
        "validation": validation,
        "audit_path": result.audit_path,
    }


def format_answer(comparisons: list[dict[str, Any]], verified: bool) -> str:
    """Render a short, human-readable cited summary of the comparison."""
    if not comparisons:
        return "No terms were defined in both sources, so no comparison was possible."
    lines = ["Definition transparency — prospectus vs. investor report:\n"]
    for c in comparisons:
        term = c.get("term", "?")
        materiality = c.get("materiality", "?")
        rationale = c.get("rationale", "")
        a_page = c.get("a_page")
        b_page = c.get("b_page")
        lines.append(f"- {term} [{materiality}]: {rationale}")
        cite = []
        if a_page is not None:
            cite.append(f"prospectus p.{a_page}")
        if b_page is not None:
            cite.append(f"investor report p.{b_page}")
        if cite:
            lines.append(f"    sources: {', '.join(cite)}")
    lines.append("")
    lines.append(
        "All citations verified against source pages." if verified
        else "WARNING: one or more citations did not verify against the sources."
    )
    return "\n".join(lines)
