"""Three Lines of Defense (3LoD) agent primitives for structured finance analysis.

Each primitive calls the LLM with a specialist system prompt and the full deal text,
plus the outputs of all prior agents. They are designed to run sequentially:
CreditAgent → RiskAgent → AuditAgent, with each building on the previous.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ..primitives.base import BasePrimitive, PrimitiveInput, PrimitiveOutput
from .prompts import AUDIT_SYSTEM, CREDIT_SYSTEM, RISK_SYSTEM

JsonLLM = Callable[..., Any]


def _pages_to_text(pages: Any) -> str:
    """Concatenate connector.text pages into a single string."""
    if isinstance(pages, list):
        parts = []
        for p in pages:
            if isinstance(p, dict):
                parts.append(str(p.get("text", "")))
            else:
                parts.append(str(p))
        return "\n\n".join(parts)
    return str(pages or "")


def _fmt_prior(label: str, output: Any) -> str:
    """Format a prior agent output dict for inclusion in a prompt."""
    if not output:
        return ""
    if isinstance(output, dict):
        try:
            text = json.dumps(output, indent=2, default=str)
            if len(text) > 2000:
                text = text[:1900] + "\n... (truncated)"
            return f"\n{label}:\n{text}\n"
        except Exception:
            return f"\n{label}: {str(output)[:1000]}\n"
    return f"\n{label}: {str(output)[:1000]}\n"


class CreditAgent(BasePrimitive):
    """1st Line of Defense: credit and structural assessment of a structured finance deal."""

    name = "lod.credit"
    version = "1.0.0"
    capability = (
        "1st Line of Defense — assesses creditworthiness of a structured finance deal. "
        "Evaluates collateral pool quality (DSCR, LTV, WA metrics), tranche structure, "
        "waterfall mechanics, credit enhancement, and originator/servicer quality. "
        "Returns RAG status (GREEN/AMBER/RED) with full credit analysis."
    )
    inputs = {
        "pages": "list[{page, text}] from connector.text containing the deal data.",
        "document": "str label for the deal data source.",
        "question": "str analyst question about the deal.",
    }
    outputs = {
        "payload.rag": "GREEN | AMBER | RED — overall credit assessment status.",
        "payload.justification": "One-sentence rationale for the RAG status.",
        "payload.analysis": "Full credit assessment narrative.",
        "payload.data_gaps": "list[str] of data items missing for a complete assessment.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from ..primitives._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages = inp.get("pages", [])
        question = str(inp.get("question", "") or "").strip()
        deal_text = _pages_to_text(pages)

        if not deal_text.strip():
            return PrimitiveOutput(
                payload=_empty_credit(),
                confidence=0.3,
                issues=["No deal data provided. Proceeding with incomplete information."],
            )

        prompt = (
            f"DEAL DATA:\n{deal_text[:8000]}\n\n"
            f"ANALYST QUESTION: {question or '(general credit assessment)'}\n\n"
            "Provide your 1st Line of Defense credit assessment."
        )

        try:
            raw = self._llm(prompt, system=CREDIT_SYSTEM, max_tokens=3000)
        except Exception as exc:
            return PrimitiveOutput(
                payload=_empty_credit(),
                confidence=0.2,
                issues=[f"LLM invocation failed: {exc}"],
            )

        if not isinstance(raw, dict):
            return PrimitiveOutput(
                payload=_empty_credit(),
                confidence=0.2,
                issues=["Unexpected response format from LLM."],
            )

        rag = str(raw.get("rag", "AMBER")).upper().strip()
        if rag not in ("GREEN", "AMBER", "RED"):
            rag = "AMBER"
        justification = str(raw.get("justification", "")).strip()
        analysis = str(raw.get("analysis", "")).strip()
        data_gaps = [str(g) for g in (raw.get("data_gaps") or []) if g]

        confidence = {"GREEN": 0.85, "AMBER": 0.70, "RED": 0.75}.get(rag, 0.70)
        if data_gaps:
            confidence = max(0.4, confidence - len(data_gaps) * 0.05)

        return PrimitiveOutput(
            payload={
                "rag": rag,
                "justification": justification,
                "analysis": analysis,
                "data_gaps": data_gaps,
            },
            confidence=round(confidence, 4),
            issues=data_gaps[:3] if data_gaps else [],
            metadata={"agent": "lod.credit", "rag": rag},
        )


class RiskAgent(BasePrimitive):
    """2nd Line of Defense: independent risk oversight for a structured finance deal."""

    name = "lod.risk"
    version = "1.0.0"
    capability = (
        "2nd Line of Defense — independent risk oversight. "
        "Assesses interest rate risk, prepayment risk, counterparty risk, concentration risk, "
        "covenant mechanics, regulatory capital (Basel IV/CRR3/STS), and stress scenarios. "
        "Receives the Credit Agent output and challenges it. "
        "Returns a risk score 1–10 with top 3 risk flags."
    )
    inputs = {
        "pages": "list[{page, text}] from connector.text containing the deal data.",
        "document": "str label for the deal data source.",
        "question": "str analyst question about the deal.",
        "credit_output": "dict payload from lod.credit — the 1st Line assessment to challenge.",
    }
    outputs = {
        "payload.score": "int 1–10 risk score (1=low, 10=very high).",
        "payload.flags": "list[str] top 3 risk flags.",
        "payload.analysis": "Full independent risk assessment narrative.",
        "payload.credit_assessment_challenge": "str where Risk agent agrees/disagrees with Credit.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from ..primitives._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages = inp.get("pages", [])
        question = str(inp.get("question", "") or "").strip()
        credit_output = inp.get("credit_output") or {}
        deal_text = _pages_to_text(pages)

        prompt = (
            f"DEAL DATA:\n{deal_text[:6000]}\n\n"
            f"ANALYST QUESTION: {question or '(general risk assessment)'}\n"
            f"{_fmt_prior('CREDIT AGENT (1st LoD) OUTPUT', credit_output)}\n"
            "Provide your 2nd Line of Defense independent risk assessment."
        )

        try:
            raw = self._llm(prompt, system=RISK_SYSTEM, max_tokens=3000)
        except Exception as exc:
            return PrimitiveOutput(
                payload=_empty_risk(),
                confidence=0.2,
                issues=[f"LLM invocation failed: {exc}"],
            )

        if not isinstance(raw, dict):
            return PrimitiveOutput(
                payload=_empty_risk(),
                confidence=0.2,
                issues=["Unexpected response format from LLM."],
            )

        score_raw = raw.get("score", 5)
        try:
            score = max(1, min(10, int(score_raw)))
        except (TypeError, ValueError):
            score = 5
        flags = [str(f) for f in (raw.get("flags") or []) if f][:3]
        analysis = str(raw.get("analysis", "")).strip()
        challenge = str(raw.get("credit_assessment_challenge", "")).strip()

        # Higher risk score → lower confidence in the deal
        confidence = max(0.3, min(0.9, 1.0 - (score - 1) / 12))

        return PrimitiveOutput(
            payload={
                "score": score,
                "flags": flags,
                "analysis": analysis,
                "credit_assessment_challenge": challenge,
            },
            confidence=round(confidence, 4),
            issues=flags[:2] if score >= 7 else [],
            metadata={"agent": "lod.risk", "score": score},
        )


class AuditAgent(BasePrimitive):
    """3rd Line of Defense: compliance and audit assessment for a structured finance deal."""

    name = "lod.audit"
    version = "1.0.0"
    capability = (
        "3rd Line of Defense — independent compliance and audit assurance. "
        "Assesses STS compliance (EU 2017/2402), SPV structural integrity (true sale, "
        "bankruptcy remoteness), AML/KYC, legal document completeness, DORA, EU Taxonomy, "
        "and trustee/investor reporting. Challenges both Credit and Risk agent outputs. "
        "Returns PASS / CONDITIONAL PASS / FAIL with specific findings."
    )
    inputs = {
        "pages": "list[{page, text}] from connector.text containing the deal data.",
        "document": "str label for the deal data source.",
        "question": "str analyst question about the deal.",
        "credit_output": "dict payload from lod.credit — the 1st Line assessment.",
        "risk_output": "dict payload from lod.risk — the 2nd Line assessment.",
    }
    outputs = {
        "payload.verdict": "PASS | CONDITIONAL PASS | FAIL — overall compliance verdict.",
        "payload.findings": "list[str] specific audit findings.",
        "payload.analysis": "Full compliance and audit assessment narrative.",
        "payload.prior_agent_challenges": "str challenges or validations of Credit and Risk outputs.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from ..primitives._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        pages = inp.get("pages", [])
        question = str(inp.get("question", "") or "").strip()
        credit_output = inp.get("credit_output") or {}
        risk_output = inp.get("risk_output") or {}
        deal_text = _pages_to_text(pages)

        prompt = (
            f"DEAL DATA:\n{deal_text[:5000]}\n\n"
            f"ANALYST QUESTION: {question or '(general audit assessment)'}\n"
            f"{_fmt_prior('CREDIT AGENT (1st LoD) OUTPUT', credit_output)}"
            f"{_fmt_prior('RISK AGENT (2nd LoD) OUTPUT', risk_output)}\n"
            "Provide your 3rd Line of Defense compliance and audit assessment."
        )

        try:
            raw = self._llm(prompt, system=AUDIT_SYSTEM, max_tokens=4096)
        except Exception as exc:
            return PrimitiveOutput(
                payload=_empty_audit(),
                confidence=0.2,
                issues=[f"LLM invocation failed: {exc}"],
            )

        if not isinstance(raw, dict):
            return PrimitiveOutput(
                payload=_empty_audit(),
                confidence=0.2,
                issues=["Unexpected response format from LLM."],
            )

        verdict = str(raw.get("verdict", "CONDITIONAL PASS")).upper().strip()
        if verdict not in ("PASS", "CONDITIONAL PASS", "FAIL"):
            verdict = "CONDITIONAL PASS"
        findings = [str(f) for f in (raw.get("findings") or []) if f]
        analysis = str(raw.get("analysis", "")).strip()
        challenges = str(raw.get("prior_agent_challenges", "")).strip()

        confidence = {"PASS": 0.85, "CONDITIONAL PASS": 0.65, "FAIL": 0.55}.get(verdict, 0.65)
        if len(findings) >= 3:
            confidence = max(0.3, confidence - 0.05 * (len(findings) - 2))

        return PrimitiveOutput(
            payload={
                "verdict": verdict,
                "findings": findings,
                "analysis": analysis,
                "prior_agent_challenges": challenges,
            },
            confidence=round(confidence, 4),
            issues=findings[:3] if verdict != "PASS" else [],
            metadata={"agent": "lod.audit", "verdict": verdict},
        )


def _empty_credit() -> dict:
    return {"rag": "AMBER", "justification": "", "analysis": "", "data_gaps": []}


def _empty_risk() -> dict:
    return {"score": 5, "flags": [], "analysis": "", "credit_assessment_challenge": ""}


def _empty_audit() -> dict:
    return {"verdict": "CONDITIONAL PASS", "findings": [], "analysis": "", "prior_agent_challenges": ""}
