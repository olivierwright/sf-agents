"""Cross-source consistency checker.

Generalises DefinitionComparator and ClaimVsCollateral: given two sets of
data extracted from different documents, checks field-by-field consistency
and flags material discrepancies.

Typical uses:
  - Compare a term's definition in the prospectus vs. the investor report
  - Check that pool stats in the prospectus match the loan tape
  - Verify that covenant thresholds in the conditions match the servicer report
  - Cross-reference reserve fund balance across documents
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a structured-finance compliance analyst specialising in cross-document "
    "consistency checks. You compare data from two sources and identify discrepancies. "
    "You assess materiality: a 0.01% numeric difference is immaterial; a missing field "
    "or inverted sign is material. Be precise and cite the exact values compared. "
    "Respond with a single JSON object only."
)


class ConsistencyAnalyzer(BasePrimitive):
    """Check consistency of extracted data across two source documents.

    Returns per-field results with discrepancy descriptions and materiality
    assessments, plus an overall consistency verdict.
    """

    name = "analyzer.consistency"
    version = "0.1.0"
    capability = (
        "Cross-check data extracted from two different source documents for consistency. "
        "Given data_a and data_b (any dicts or lists from upstream extractors), compares "
        "matching fields and flags material discrepancies. Returns per-field results with "
        "values from both sources, consistency verdict, discrepancy description, and "
        "materiality (low/medium/high). Use to verify that the prospectus, investor report, "
        "and loan tape agree on key values (pool balances, tranche amounts, reserve fund, etc.)."
    )
    inputs = {
        "data_a": "any: data from source A (dict, list, or extracted payload).",
        "label_a": "str: human-readable label for source A (e.g. 'Prospectus').",
        "data_b": "any: data from source B.",
        "label_b": "str: human-readable label for source B (e.g. 'Investor Report').",
        "fields": "list[str], optional: specific field names to check. If omitted, checks all common keys.",
    }
    outputs = {
        "payload.results": "list[{field, value_a, value_b, consistent, discrepancy_description, materiality}].",
        "payload.overall_consistent": "bool: True if no material discrepancies found.",
        "payload.material_issues": "list[str]: fields with high/medium materiality discrepancies.",
        "payload.label_a": "str: echoed source A label.",
        "payload.label_b": "str: echoed source B label.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        data_a: Any = inp.get("data_a")
        data_b: Any = inp.get("data_b")
        label_a: str = str(inp.get("label_a", "Source A") or "Source A").strip()
        label_b: str = str(inp.get("label_b", "Source B") or "Source B").strip()
        fields: Optional[list[str]] = inp.get("fields")

        if data_a is None or data_b is None:
            return PrimitiveOutput(
                payload=self._empty(label_a, label_b),
                citations=[], confidence=0.0,
                issues=["Both data_a and data_b are required."],
            )

        fields_hint = ""
        if fields:
            fields_hint = f"\nFIELDS TO CHECK: {', '.join(fields)}\n"

        a_text = _compact(data_a)
        b_text = _compact(data_b)

        prompt = (
            f"SOURCE A ({label_a}):\n{a_text}\n\n"
            f"SOURCE B ({label_b}):\n{b_text}\n"
            f"{fields_hint}\n"
            "TASK: Compare the data from the two sources. For each comparable field, "
            "check whether the values are consistent. Assess materiality:\n"
            "  high — sign error, order-of-magnitude difference, missing required field\n"
            "  medium — value differs by >5% or meaningful semantic difference\n"
            "  low — minor formatting, rounding, or immaterial numeric difference\n\n"
            "Return JSON:\n"
            "{\n"
            '  "results": [\n'
            "    {\n"
            '      "field": str,\n'
            f'      "value_a": str,\n'
            f'      "value_b": str,\n'
            '      "consistent": bool,\n'
            '      "discrepancy_description": str,\n'
            '      "materiality": "low"|"medium"|"high"\n'
            "    }\n"
            "  ],\n"
            '  "overall_consistent": bool,\n'
            '  "summary": str\n'
            "}\n"
        )

        try:
            raw = self._llm(prompt, system=_SYSTEM, max_tokens=2000)
        except Exception as exc:
            return PrimitiveOutput(
                payload=self._empty(label_a, label_b),
                citations=[], confidence=0.0,
                issues=[f"LLM consistency check failed: {exc}"],
            )

        if not isinstance(raw, dict):
            return PrimitiveOutput(
                payload=self._empty(label_a, label_b),
                citations=[], confidence=0.0,
                issues=["Consistency check returned unexpected format."],
            )

        raw_results = raw.get("results", []) or []
        results: list[dict] = []
        for r in raw_results:
            if not isinstance(r, dict):
                continue
            results.append({
                "field": str(r.get("field", "")),
                "value_a": str(r.get("value_a", "")),
                "value_b": str(r.get("value_b", "")),
                "consistent": bool(r.get("consistent", True)),
                "discrepancy_description": str(r.get("discrepancy_description", "")),
                "materiality": str(r.get("materiality", "low")),
            })

        overall = bool(raw.get("overall_consistent", True))
        material_issues = [
            r["field"] for r in results
            if not r["consistent"] and r["materiality"] in ("medium", "high")
        ]

        n_checked = len(results)
        n_consistent = sum(1 for r in results if r["consistent"])
        confidence = round(n_consistent / max(n_checked, 1), 4) if n_checked else 0.5

        citations: list[Citation] = []
        for r in results:
            if not r["consistent"] and r.get("discrepancy_description"):
                citations.append(Citation(
                    source=f"{label_a} vs {label_b}",
                    location=f"field={r['field']}",
                    excerpt=r["discrepancy_description"][:240],
                ))

        return PrimitiveOutput(
            payload={
                "results": results,
                "overall_consistent": overall,
                "material_issues": material_issues,
                "label_a": label_a,
                "label_b": label_b,
                "summary": str(raw.get("summary", "")),
            },
            citations=citations,
            confidence=confidence,
            issues=[f"Material discrepancy in: {', '.join(material_issues)}"] if material_issues else [],
            metadata={
                "fields_checked": n_checked,
                "consistent": n_consistent,
                "material_issues": len(material_issues),
            },
        )

    @staticmethod
    def _empty(label_a: str, label_b: str) -> dict:
        return {
            "results": [],
            "overall_consistent": True,
            "material_issues": [],
            "label_a": label_a,
            "label_b": label_b,
            "summary": "",
        }


def _compact(data: Any) -> str:
    """Compact data to a string for LLM consumption."""
    import json
    if isinstance(data, str):
        return data[:3000]
    try:
        text = json.dumps(data, default=str, indent=2)
        return text[:3000] + ("\n... (truncated)" if len(text) > 3000 else "")
    except Exception:
        return str(data)[:3000]
