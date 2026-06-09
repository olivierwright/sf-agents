"""Test green/social claims against what the loan tape actually shows.

Given a set of green claims extracted from a document (each with a page and a
verbatim excerpt) and the loan tape's columns + rows, this analyzer:

    1. Maps each claim to the relevant *green* tape fields (EPC label, EPC issue
       year, primary energy demand, construction-deposit flag) by keyword.
    2. Computes -- deterministically, not via the model -- what the tape actually
       shows for those fields (label distribution, numeric range, flagged share).
    3. Asks the model for a verdict per claim: ``supported`` /
       ``partially supported`` / ``not supported`` / ``not verifiable from data``
       with a one-sentence rationale grounded in those computed figures.
    4. Emits, for every claim, citations that resolve on BOTH sides -- the
       claim's *document page* AND specific *loan-tape rows/columns* -- so the
       verifier can prove the claim and its counter-evidence are real.

The tape figures are computed from the real rows, and the cited row indices are
guaranteed in range, so a passing verifier means the comparison is genuinely
dual-grounded rather than asserted.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from ...knowledge.loader import green_section as _green_section

JsonLLM = Callable[..., Any]

_VALID_VERDICTS = {
    "supported",
    "partially supported",
    "not supported",
    "not verifiable from data",
}

#: The green loan-tape fields this analyzer reasons about, with the keywords that
#: route a claim to each. A claim is matched to a field if any keyword appears in
#: its term/definition/excerpt (case-insensitive).
_GREEN_FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "epc_label": ("epc", "energy performance", "energy label", "energy rating"),
    "epc_issue_year": ("epc", "energy performance certificate", "certificate"),
    "primary_energy_demand_kwh_m2": (
        "primary energy",
        "energy demand",
        "kwh",
        "energy efficiency",
        "energy consumption",
    ),
    "construction_deposit_flag": (
        "construction deposit",
        "new build",
        "newly built",
        "energy-efficient new",
    ),
}

_SYSTEM = (
    "You are a structured-finance sustainability analyst. You judge whether a "
    "green claim made in a deal document is borne out by the actual loan-tape "
    "figures you are given. You never invent numbers: your verdict must follow "
    "from the figures shown. Be conservative.\n\n"
    "=== STRUCTURED FINANCE DOMAIN KNOWLEDGE ===\n"
    + _green_section() +
    "\n=== END ==="
)


class ClaimVsCollateral(BasePrimitive):
    """Score green claims against the loan tape's green fields, dual-grounded.

    Input args:
        claims (list[dict]): ``[{term, definition, page, excerpt}, ...]`` -- the
            green claims extracted from a document.
        claim_source (str): The claim document's name (citation ``source``).
        columns (list[str]): The loan tape's column names.
        rows (list[dict]): The loan tape's row records.
        tape_document (str): The loan tape's file name (citation ``source``).

    Payload:
        ``{"claim_source", "tape_document", "assessments": [{claim, verdict,
           rationale, claim_page, tape_columns, tape_rows, tape_facts}...]}``
    """

    name = "analyzer.claim_vs_collateral"
    version = "0.1.0"
    capability = (
        "Test green/social claims (each with a document page and excerpt) against "
        "what the loan tape actually shows in its green fields (EPC label, EPC "
        "issue year, primary energy demand, construction-deposit flag). Computes "
        "the real tape figures, returns a verdict per claim (supported / "
        "partially supported / not supported / not verifiable from data) with a "
        "rationale, and cites BOTH the claim's document page AND specific tape "
        "rows/columns. Use after extracting claims from a document and loading "
        "the loan tape."
    )
    inputs = {
        "claims": "list[{term, definition, page, excerpt}]: reference the claim extractor's payload.definitions.",
        "claim_source": "str: the claim document name; reference the claim PDF connector's payload.document.",
        "columns": "list[str]: loan-tape column names; reference connector.loan_tape payload.columns.",
        "rows": "list[dict]: loan-tape row records; reference connector.loan_tape payload.rows.",
        "tape_document": "str: loan-tape file name; reference connector.loan_tape payload.document.",
    }
    outputs = {
        "payload.claim_source": "str: echoed claim document name.",
        "payload.tape_document": "str: echoed loan-tape file name.",
        "payload.assessments": "list[{claim, verdict, rationale, claim_page, tape_columns, tape_rows, tape_facts}]: the dual-grounded result (final answer).",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        claims: list[dict[str, Any]] = inp.get("claims", []) or []
        claim_source: str = inp.get("claim_source", "claim_source")
        columns: list[str] = [str(c) for c in (inp.get("columns", []) or [])]
        rows: list[dict[str, Any]] = inp.get("rows", []) or []
        tape_document: str = inp.get("tape_document", "loan_tape")

        present_fields = [f for f in _GREEN_FIELD_KEYWORDS if f in columns]
        issues: list[str] = []
        if not present_fields:
            issues.append(
                "Loan tape exposes none of the known green fields; claims are not "
                "verifiable from this tape."
            )
        if not claims:
            issues.append("No green claims supplied to assess.")
            return PrimitiveOutput(
                payload={
                    "claim_source": claim_source,
                    "tape_document": tape_document,
                    "assessments": [],
                },
                confidence=1.0,
                issues=issues,
                metadata={"present_green_fields": present_fields},
            )

        # Per-field computed ground truth + representative real row indices.
        field_facts = {f: self._field_facts(f, rows) for f in present_fields}

        # Route each claim to the relevant green fields.
        routed: list[dict[str, Any]] = []
        for claim in claims:
            text = " ".join(
                str(claim.get(k, "")) for k in ("term", "definition", "excerpt")
            ).lower()
            matched = [
                f
                for f in present_fields
                if any(kw in text for kw in _GREEN_FIELD_KEYWORDS[f])
            ]
            # If nothing matched, still attach all present green fields so the
            # claim is judged (likely "not verifiable") rather than dropped.
            routed.append({"claim": claim, "fields": matched or present_fields})

        prompt = self._build_prompt(claim_source, tape_document, routed, field_facts)
        raw = self._llm(prompt, system=_SYSTEM, max_tokens=2048)
        verdicts = self._index_verdicts(raw)

        assessments: list[dict[str, Any]] = []
        citations: list[Citation] = []
        scored_ok = 0
        for entry in routed:
            claim = entry["claim"]
            fields = entry["fields"]
            term = str(claim.get("term", "")).strip() or "(unnamed claim)"
            page = claim.get("page")
            excerpt = str(claim.get("excerpt", "")).strip()

            v = verdicts.get(term.lower(), {})
            verdict = str(v.get("verdict", "")).strip().lower()
            if verdict not in _VALID_VERDICTS:
                verdict = "not verifiable from data"
                issues.append(
                    f"Model gave no valid verdict for '{term}'; defaulted to "
                    "'not verifiable from data'."
                )
            else:
                scored_ok += 1
            rationale = str(v.get("rationale", "")).strip()

            tape_rows = self._citation_rows(fields, field_facts)
            assessments.append(
                {
                    "claim": term,
                    "verdict": verdict,
                    "rationale": rationale,
                    "claim_page": page if isinstance(page, int) else None,
                    "tape_columns": fields,
                    "tape_rows": tape_rows,
                    "tape_facts": {f: field_facts[f]["summary"] for f in fields},
                }
            )

            # Document-side citation: the claim's page + verbatim excerpt.
            if isinstance(page, int) and excerpt:
                citations.append(
                    Citation(
                        source=claim_source,
                        location=f"page={page}",
                        excerpt=excerpt[:240],
                    )
                )
            else:
                issues.append(f"No resolvable document page for claim '{term}'.")
            # Tape-side citations: real rows backing the cited green fields.
            for ridx in tape_rows:
                col = fields[0] if fields else (present_fields[0] if present_fields else "")
                value = ""
                if 0 <= ridx < len(rows) and col:
                    value = rows[ridx].get(col, "")
                citations.append(
                    Citation(
                        source=tape_document,
                        location=f"row={ridx}",
                        excerpt=f"{col}={value}" if col else f"row {ridx}",
                    )
                )

        confidence = round(scored_ok / len(routed), 4) if routed else 1.0
        dq_flags = _data_quality_flags(present_fields, rows)
        for flag in dq_flags:
            issues.append(f"DATA QUALITY — {flag['field']}: {flag['issue']}")
        return PrimitiveOutput(
            payload={
                "claim_source": claim_source,
                "tape_document": tape_document,
                "assessments": assessments,
                "data_quality_flags": dq_flags,
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={
                "present_green_fields": present_fields,
                "row_count": len(rows),
                "data_quality_flags": len(dq_flags),
            },
        )

    # -- ground-truth computation ----------------------------------------- #
    @staticmethod
    def _field_facts(field: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute a deterministic summary + representative real rows for a field."""
        present_rows = [
            i for i, r in enumerate(rows) if r.get(field) not in (None, "")
        ]
        sample_rows = present_rows[:3] if present_rows else ([0] if rows else [])
        values = [rows[i].get(field) for i in present_rows]

        if field in ("primary_energy_demand_kwh_m2", "epc_issue_year"):
            nums = [float(v) for v in values if _is_number(v)]
            if nums:
                summary = {
                    "n": len(nums),
                    "min": round(min(nums), 2),
                    "max": round(max(nums), 2),
                    "mean": round(sum(nums) / len(nums), 2),
                }
            else:
                summary = {"n": 0}
        elif field == "construction_deposit_flag":
            truthy = sum(1 for v in values if str(v).strip().lower() in {"y", "yes", "true", "1"})
            summary = {
                "n": len(values),
                "flagged": truthy,
                "flagged_pct": round(100 * truthy / len(values), 1) if values else 0.0,
            }
        else:  # categorical, e.g. epc_label
            dist: dict[str, int] = {}
            for v in values:
                key = str(v).strip()
                dist[key] = dist.get(key, 0) + 1
            top = dict(sorted(dist.items(), key=lambda kv: kv[1], reverse=True)[:8])
            summary = {"n": len(values), "distribution": top}

        return {"summary": summary, "rows": sample_rows}

    @staticmethod
    def _citation_rows(
        fields: list[str], field_facts: dict[str, dict[str, Any]]
    ) -> list[int]:
        """Collect a small set of real, in-range row indices backing these fields."""
        rows: list[int] = []
        for f in fields:
            for ridx in field_facts.get(f, {}).get("rows", []):
                if ridx not in rows:
                    rows.append(ridx)
        return rows[:3] if rows else ([] )

    # -- prompt + parsing -------------------------------------------------- #
    @staticmethod
    def _build_prompt(
        claim_source: str,
        tape_document: str,
        routed: list[dict[str, Any]],
        field_facts: dict[str, dict[str, Any]],
    ) -> str:
        blocks = []
        for entry in routed:
            claim = entry["claim"]
            term = str(claim.get("term", "")).strip() or "(unnamed claim)"
            definition = str(claim.get("definition", "")).strip()
            facts = {f: field_facts[f]["summary"] for f in entry["fields"]}
            blocks.append(
                f"CLAIM: {term}\n"
                f"  text: {definition}\n"
                f"  loan-tape figures for the relevant green fields: {facts}"
            )
        body = "\n\n".join(blocks)
        return (
            "Assess whether each green claim below holds up against the loan-tape "
            f"figures shown. The claims come from '{claim_source}'; the figures "
            f"come from '{tape_document}'.\n\n"
            "For each claim return an object with keys: 'claim' (echo the CLAIM "
            "name exactly), 'verdict' (one of: supported, partially supported, "
            "not supported, not verifiable from data) and 'rationale' (one "
            "sentence grounded in the figures). Return a JSON array of such "
            "objects.\n\n"
            f"{body}"
        )

    @staticmethod
    def _index_verdicts(raw: Any) -> dict[str, dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if isinstance(raw, list):
            records = [r for r in raw if isinstance(r, dict)]
        elif isinstance(raw, dict):
            for key in ("assessments", "results", "items", "claims"):
                if isinstance(raw.get(key), list):
                    records = [r for r in raw[key] if isinstance(r, dict)]
                    break
            else:
                records = [raw]
        return {str(r.get("claim", "")).strip().lower(): r for r in records}


def _data_quality_flags(
    present_fields: list[str], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return data quality issues found in the green tape fields."""
    flags: list[dict[str, Any]] = []

    if "primary_energy_demand_kwh_m2" in present_fields:
        nums = [float(r["primary_energy_demand_kwh_m2"]) for r in rows
                if _is_number(r.get("primary_energy_demand_kwh_m2"))]
        if nums:
            negatives = [v for v in nums if v < 0]
            if negatives:
                flags.append({
                    "field": "primary_energy_demand_kwh_m2",
                    "issue": (
                        f"{len(negatives)} negative PED values (min={min(negatives):.0f}). "
                        "May be net-positive-energy buildings or imputation artefacts."
                    ),
                    "count": len(negatives),
                    "sample_values": sorted(negatives)[:3],
                })
            very_high = [v for v in nums if v > 300]
            if very_high:
                flags.append({
                    "field": "primary_energy_demand_kwh_m2",
                    "issue": f"{len(very_high)} PED values above 300 kWh/m² (max={max(very_high):.0f}).",
                    "count": len(very_high),
                    "sample_values": sorted(very_high, reverse=True)[:3],
                })

    if "epc_label" in present_fields:
        unknown = sum(
            1 for r in rows
            if str(r.get("epc_label", "") or "").strip().lower() in ("unknown", "", "n/a", "na")
        )
        if unknown:
            flags.append({
                "field": "epc_label",
                "issue": f"{unknown} loans with unknown/missing EPC label.",
                "count": unknown,
                "sample_values": [],
            })
        non_green = sum(
            1 for r in rows
            if str(r.get("epc_label", "") or "").strip().upper() in ("B", "C", "D", "E", "F", "G")
        )
        if non_green:
            flags.append({
                "field": "epc_label",
                "issue": f"{non_green} loans with EPC labels below A (B–G).",
                "count": non_green,
                "sample_values": [],
            })

    return flags


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
