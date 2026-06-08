"""Recipe: Three Lines of Defense (3LoD) structured finance analysis.

Runs a sequential assessment pipeline against the loaded deal documents:
    connector.prospectus  →  lod.credit  →  lod.risk  →  lod.audit

The plan is always hardcoded (no LLM planner invocation). The agents read
the prospectus pages directly and assess the deal from that source data.
"""

from __future__ import annotations

from ..config import get_config
from ..orchestrator.planner import Plan, Step

PROSPECTUS_FILE = "green-lion-2026-1-prospectus.pdf"
INVESTOR_REPORT_FILE = "monthly-investor-report-green-lion-2026-1-april-2026.pdf"

DEFAULT_QUESTION = (
    "Provide a full Three Lines of Defense assessment of this deal: "
    "credit quality, structural risks, and regulatory compliance."
)


def _ref(step_id: str, path: str) -> dict[str, str]:
    """A plan reference object resolving to an upstream step's output value."""
    return {"$from": step_id, "path": path}


def get_lod_recipe(question: str = "", deal_data: str = "") -> tuple[str, dict, Plan]:
    """Return (question, planner_context, hardcoded_plan) for the 3LoD recipe.

    Loads deal documents from the configured data directory.  ``deal_data`` is
    ignored — the recipe always reads from the actual deal files so the agents
    work with the same source as every other recipe.

    Returns:
        A 3-tuple of (question, context_dict, Plan) ready for _run_question_worker.
    """
    cfg = get_config()
    q = question.strip() or DEFAULT_QUESTION

    try:
        prospectus_path = str(cfg.deal_file(PROSPECTUS_FILE))
    except FileNotFoundError:
        prospectus_path = None

    try:
        ir_path = str(cfg.deal_file(INVESTOR_REPORT_FILE))
    except FileNotFoundError:
        ir_path = None

    if prospectus_path:
        # Primary flow: load from actual deal documents
        steps = [
            Step(
                "prospectus_load",
                "connector.prospectus",
                {"path": prospectus_path},
                depends_on=[],
            ),
        ]
        if ir_path:
            steps.append(Step(
                "ir_load",
                "connector.investor_report",
                {"path": ir_path},
                depends_on=[],
            ))
        steps += [
            Step(
                "lod_credit",
                "lod.credit",
                {
                    "pages": _ref("prospectus_load", "payload.pages"),
                    "document": _ref("prospectus_load", "payload.document"),
                    "question": q,
                },
                depends_on=["prospectus_load"],
            ),
            Step(
                "lod_risk",
                "lod.risk",
                {
                    "pages": _ref("prospectus_load", "payload.pages"),
                    "document": _ref("prospectus_load", "payload.document"),
                    "question": q,
                    "credit_output": _ref("lod_credit", "payload"),
                },
                depends_on=["lod_credit"],
            ),
            Step(
                "lod_audit",
                "lod.audit",
                {
                    "pages": _ref("prospectus_load", "payload.pages"),
                    "document": _ref("prospectus_load", "payload.document"),
                    "question": q,
                    "credit_output": _ref("lod_credit", "payload"),
                    "risk_output": _ref("lod_risk", "payload"),
                },
                depends_on=["lod_risk"],
            ),
        ]
        context: dict = {
            "documents": {"prospectus": prospectus_path},
        }
    else:
        # Fallback: no deal files found — run with empty placeholder
        steps = [
            Step("deal_load", "connector.text",
                 {"text": "(no deal data available)", "document": "deal_data"}),
            Step("lod_credit", "lod.credit", {
                "pages": _ref("deal_load", "payload.pages"),
                "document": _ref("deal_load", "payload.document"),
                "question": q,
            }, depends_on=["deal_load"]),
            Step("lod_risk", "lod.risk", {
                "pages": _ref("deal_load", "payload.pages"),
                "document": _ref("deal_load", "payload.document"),
                "question": q,
                "credit_output": _ref("lod_credit", "payload"),
            }, depends_on=["lod_credit"]),
            Step("lod_audit", "lod.audit", {
                "pages": _ref("deal_load", "payload.pages"),
                "document": _ref("deal_load", "payload.document"),
                "question": q,
                "credit_output": _ref("lod_credit", "payload"),
                "risk_output": _ref("lod_risk", "payload"),
            }, depends_on=["lod_risk"]),
        ]
        context = {}

    plan = Plan(
        steps=steps,
        explanation=(
            "Three Lines of Defense sequential assessment: "
            "1st LoD credit analysis → 2nd LoD risk oversight → 3rd LoD audit assurance."
        ),
        source="recipe",
    )
    return q, context, plan


def collect_lod_outputs(outputs: dict) -> dict:
    """Extract the three agent payloads from executor outputs."""
    return {
        "credit": outputs["lod_credit"].payload if "lod_credit" in outputs else {},
        "risk": outputs["lod_risk"].payload if "lod_risk" in outputs else {},
        "audit": outputs["lod_audit"].payload if "lod_audit" in outputs else {},
    }


def format_lod_answer(lod: dict, consolidated_verdict: str, verified: bool) -> str:
    """Render a human-readable 3LoD summary for the answer tab."""
    credit = lod.get("credit", {})
    risk = lod.get("risk", {})
    audit = lod.get("audit", {})

    lines: list[str] = ["# Three Lines of Defense Assessment\n"]

    rag = credit.get("rag", "N/A")
    lines.append(f"## 1st Line — Credit [{rag}]")
    if credit.get("justification"):
        lines.append(credit["justification"])
    if credit.get("analysis"):
        lines.append(f"\n{credit['analysis']}")
    if credit.get("data_gaps"):
        lines.append("\n**Data gaps:** " + "; ".join(credit["data_gaps"][:5]))
    lines.append("")

    score = risk.get("score", "N/A")
    lines.append(f"## 2nd Line — Risk [Score: {score}/10]")
    if risk.get("flags"):
        for flag in risk["flags"][:3]:
            lines.append(f"- {flag}")
    if risk.get("analysis"):
        lines.append(f"\n{risk['analysis']}")
    lines.append("")

    verdict = audit.get("verdict", "N/A")
    lines.append(f"## 3rd Line — Audit [{verdict}]")
    if audit.get("findings"):
        for finding in audit["findings"][:5]:
            lines.append(f"- {finding}")
    if audit.get("analysis"):
        lines.append(f"\n{audit['analysis']}")
    lines.append("")

    lines.append("## Investment Committee Verdict")
    lines.append(consolidated_verdict or "(synthesis pending)")
    lines.append("")
    if not verified:
        lines.append("*Note: citation verification skipped for free-text deal data.*")

    return "\n".join(lines)
