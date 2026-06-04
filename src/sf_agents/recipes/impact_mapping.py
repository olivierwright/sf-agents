"""Recipe: *impact mapping* -- do the green claims hold up against the collateral?

Question it answers:
    "Do the green/social claims made in the prospectus and the ISS second-party
    opinion actually hold up against the loan tape, and are the CFP impact
    report's figures consistent with what the tape shows?"

Each claim document (prospectus, ISS SPO, CFP impact report) is read as a PDF,
its green claims are extracted with their page numbers, and every claim is then
tested against the *real* loan-tape green fields (EPC label, EPC issue year,
primary energy demand, construction-deposit flag). The verdict for each claim is
dual-grounded: it cites BOTH the claim's document page AND the specific loan-tape
rows/columns that back (or contradict) it. The verifier fails the run if either
side of any citation does not resolve.

    connector.pdf_document (prospectus) ─► extractor.definitions ─┐
    connector.pdf_document (spo)        ─► extractor.definitions ─┼─► analyzer.
    connector.pdf_document (cfp)        ─► extractor.definitions ─┤    claim_vs_
    connector.loan_tape  ───────────────────────────────────────┘    collateral

The planner is asked to produce this DAG live; if the LLM is unavailable or
returns an invalid plan, the deterministic fallback below runs instead and the
chosen path is logged.
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

# Green/social terms to look for in the claim documents. They map (by keyword,
# inside the analyzer) onto the loan tape's green fields.
DEFAULT_GREEN_TERMS = [
    "EPC label",
    "primary energy demand",
    "construction deposit",
    "energy efficiency",
]

PROSPECTUS_FILE = "green-lion-2026-1-prospectus.pdf"
SPO_FILE = "green-lion-2026-1-iss-second-party-opinion-spo.pdf"
CFP_FILE = "green-lion-2026-1-cfp-impact-report.pdf"
LOAN_TAPE_FILE = "green_lion_2026_1_synthetic_loan_tape.csv"

QUESTION = (
    "Do the green/social claims made in the prospectus and the ISS second-party "
    "opinion actually hold up against the loan tape, and are the CFP impact "
    "report's figures consistent with what the tape shows?"
)

# (step_id suffix, file constant) for the three claim documents.
_CLAIM_DOCS = [
    ("prospectus", PROSPECTUS_FILE),
    ("spo", SPO_FILE),
    ("cfp", CFP_FILE),
]


def _ref(step_id: str, path: str) -> dict[str, str]:
    """A plan reference object resolving to an upstream step's output value."""
    return {"$from": step_id, "path": path}


def build_fallback_plan(
    *,
    claim_doc_paths: dict[str, str],
    loan_tape_path: str,
    terms: list[str],
) -> Plan:
    """The deterministic, proven DAG used when the LLM planner is unavailable."""
    steps: list[Step] = [
        Step("tape_load", "connector.loan_tape", {"path": loan_tape_path}),
    ]
    for suffix, _file in _CLAIM_DOCS:
        load_id = f"{suffix}_load"
        claims_id = f"{suffix}_claims"
        assess_id = f"{suffix}_assess"
        steps.append(
            Step(load_id, "connector.pdf_document", {"path": claim_doc_paths[suffix]})
        )
        steps.append(
            Step(
                claims_id,
                "extractor.definitions",
                {
                    "pages": _ref(load_id, "payload.pages"),
                    "terms": list(terms),
                    "document": _ref(load_id, "payload.document"),
                },
                depends_on=[load_id],
            )
        )
        steps.append(
            Step(
                assess_id,
                "analyzer.claim_vs_collateral",
                {
                    "claims": _ref(claims_id, "payload.definitions"),
                    "claim_source": _ref(claims_id, "payload.document"),
                    "columns": _ref("tape_load", "payload.columns"),
                    "rows": _ref("tape_load", "payload.rows"),
                    "tape_document": _ref("tape_load", "payload.document"),
                },
                depends_on=[claims_id, "tape_load"],
            )
        )
    return Plan(
        steps=steps,
        explanation=(
            "Load the loan tape and each claim document (prospectus, ISS SPO, CFP "
            "impact report); extract their green claims with page numbers; then "
            "test every claim against the loan tape's green fields, citing both "
            "the claim page and the backing tape rows."
        ),
        source="fallback",
    )


def run_impact_mapping(
    *,
    config: Optional[Config] = None,
    llm: Optional[Callable[..., Any]] = None,
    terms: Optional[list[str]] = None,
    run_id: Optional[str] = None,
    use_planner: bool = True,
) -> dict[str, Any]:
    """Run the impact-mapping recipe end to end and return a cited result.

    Args:
        config: Override configuration (defaults to :func:`get_config`).
        llm: JSON-LLM callable injected into the planner and LLM primitives.
            Pass a mock for offline runs/tests; defaults to the real client.
        terms: Green terms to look for (defaults to :data:`DEFAULT_GREEN_TERMS`).
        run_id: Stable run identifier (defaults to a uuid4 hex).
        use_planner: If False, skip the LLM planner and run the fallback DAG.

    Returns:
        A dict with keys: ``run_id``, ``plan`` (dict), ``answer`` (str),
        ``assessments`` (list), ``verification`` (dict), ``review_queue`` (list)
        and ``audit_path`` (str).
    """
    cfg = config or get_config()
    terms = terms or list(DEFAULT_GREEN_TERMS)
    run_id = run_id or uuid.uuid4().hex[:12]

    claim_doc_paths = {
        suffix: str(cfg.deal_file(file)) for suffix, file in _CLAIM_DOCS
    }
    loan_tape_path = str(cfg.deal_file(LOAN_TAPE_FILE))

    registry = build_default_registry(llm=llm)
    fallback = build_fallback_plan(
        claim_doc_paths=claim_doc_paths,
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
                    "prospectus": claim_doc_paths["prospectus"],
                    "spo": claim_doc_paths["spo"],
                    "cfp": claim_doc_paths["cfp"],
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

    assessments = _collect_assessments(result.outputs)

    return {
        "run_id": run_id,
        "plan": plan.as_dict(),
        "answer": format_answer(assessments, report.ok),
        "assessments": assessments,
        "verification": report.as_dict(),
        "review_queue": result.review_queue,
        "audit_path": result.audit_path,
    }


def _collect_assessments(outputs) -> list[dict[str, Any]]:
    """Merge the assessments from every claim_vs_collateral step in the plan."""
    merged: list[dict[str, Any]] = []
    for output in outputs.values():
        payload = output.payload
        if isinstance(payload, dict) and isinstance(payload.get("assessments"), list):
            claim_source = payload.get("claim_source", "?")
            tape_document = payload.get("tape_document", "?")
            for a in payload["assessments"]:
                merged.append({**a, "claim_source": claim_source, "tape_document": tape_document})
    return merged


def format_answer(assessments: list[dict[str, Any]], verified: bool) -> str:
    """Render a short, human-readable cited summary of the impact mapping."""
    if not assessments:
        return (
            "No green claims were extracted from the documents, so nothing could "
            "be tested against the loan tape."
        )
    lines = ["Impact mapping — green claims vs. loan-tape reality:\n"]
    for a in assessments:
        claim = a.get("claim", "?")
        verdict = a.get("verdict", "?")
        rationale = a.get("rationale", "")
        source = a.get("claim_source", "?")
        page = a.get("claim_page")
        cols = ", ".join(a.get("tape_columns", []) or [])
        rows = ", ".join(str(r) for r in (a.get("tape_rows", []) or []))
        lines.append(f"- {claim} [{verdict}] (from {source}): {rationale}")
        cite_doc = f"{source} p.{page}" if page is not None else f"{source} (no page)"
        cite_tape = f"tape {cols} rows {rows}" if cols else "tape (no field)"
        lines.append(f"    grounded in: {cite_doc}  +  {cite_tape}")
    lines.append("")
    lines.append(
        "All citations verified against source pages and tape rows." if verified
        else "WARNING: one or more citations did not verify against the sources."
    )
    return "\n".join(lines)
