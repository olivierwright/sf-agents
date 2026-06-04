"""Deterministic green eligibility compliance checker for loan tapes.

Applies extracted green criteria (EPC thresholds, PED limits) to every row
in the loan tape and returns exact pass/fail counts per criterion. No LLM
required — pure arithmetic and label ordering.

This primitive exists because LLM-based claim assessment is appropriate for
judging whether a qualitative claim is plausible, but it is NOT the right
tool for counting how many of 3,237 loans meet a ≤27 kWh/m² threshold.
That is a deterministic calculation.

Typical use in a green claims verification plan:
  1. extractor.general extracts the thresholds from the prospectus
     (epc_label_threshold, primary_energy_demand_threshold, etc.)
  2. analyzer.tape_greencheck applies them to the loan tape
  3. The result feeds into the synthesis with exact numbers

Supported condition types:
  gte_label   — categorical: value must be ≥ threshold in the EPC label order
  lte_numeric — numeric: value must be ≤ threshold
  gte_numeric — numeric: value must be ≥ threshold
  equals      — exact string/value match
  not_null    — field must have a non-null, non-empty, non-'Unknown' value
  in_set      — value must be in a comma-separated list of allowed values

Segment-aware: each criterion can be scoped to a subset of loans by
specifying segment_field + segment_value (e.g., only check PED for houses).
"""

from __future__ import annotations

import math
from typing import Any, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

# NL EPC label hierarchy (highest to lowest energy performance)
_EPC_ORDER = ["A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]
_EPC_RANK: dict[str, int] = {label: i for i, label in enumerate(_EPC_ORDER)}

# Fields where negative values are implausible data quality issues
_IMPLAUSIBLE_NEGATIVE_FIELDS = {
    "primary_energy_demand_kwh_m2",
    "current_balance",
    "original_balance",
    "indexed_market_value",
    "current_original_market_value",
    "epc_issue_year",
}

# Reasonable numeric range for PED (kWh/m²/year)
_PED_PLAUSIBLE_RANGE = (-50, 600)  # net-positive energy buildings can be slightly negative


class TapeGreencheckAnalyzer(BasePrimitive):
    """Deterministic green eligibility compliance checker.

    Applies extracted criteria to every loan in the tape and returns exact
    pass/fail counts, data quality flags, and a human-readable summary.
    No LLM is required.
    """

    name = "analyzer.tape_greencheck"
    version = "0.1.0"
    capability = (
        "Deterministically apply green eligibility criteria to a loan tape and return "
        "exact pass/fail counts per criterion. Accepts criteria as a list of dicts with "
        "fields: name, field, condition (gte_label/lte_numeric/gte_numeric/equals/not_null/in_set), "
        "threshold, optional segment_field/segment_value, description. "
        "Also flags data quality issues (negative PED, unknown EPC, expired certificates). "
        "Use after extracting green thresholds from a prospectus with extractor.general, "
        "passing those thresholds as criteria against connector.loan_tape rows. "
        "No LLM required — results are deterministic and fully reproducible."
    )
    inputs = {
        "columns": "list[str]: loan tape column names from connector.loan_tape payload.columns.",
        "rows": "list[dict]: loan tape rows from connector.loan_tape payload.rows.",
        "tape_document": "str: loan tape file name from connector.loan_tape payload.document.",
        "criteria": (
            "list[dict]: criteria to check. Each dict: "
            "{name:str, field:str, condition:str, threshold:str|float, "
            "segment_field:str (opt), segment_value:str (opt), description:str}"
        ),
    }
    outputs = {
        "payload.results": (
            "list[{criterion_name, description, field, condition, threshold, "
            "n_total, n_applicable, n_pass, n_fail, n_missing, pass_rate, "
            "sample_failures, data_quality_flags}]: per-criterion compliance results."
        ),
        "payload.overall_pass_rate": "float: fraction of applicable checks that passed across all criteria.",
        "payload.data_quality_flags": "list[{field, issue, count, sample_values}]: data quality problems found.",
        "payload.summary": "str: human-readable compliance summary.",
        "payload.tape_document": "str: echoed tape document name.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        columns: list[str] = list(inp.get("columns", []) or [])
        rows: list[dict[str, Any]] = list(inp.get("rows", []) or [])
        tape_document: str = str(inp.get("tape_document", "loan_tape") or "loan_tape")
        criteria: list[dict[str, Any]] = list(inp.get("criteria", []) or [])

        issues: list[str] = []

        if not rows:
            return PrimitiveOutput(
                payload=self._empty(tape_document),
                citations=[], confidence=0.0,
                issues=["No loan tape rows provided."],
            )

        # Run per-criterion checks
        results: list[dict[str, Any]] = []
        for crit in criteria:
            result = self._check_criterion(crit, rows, columns, issues)
            if result:
                results.append(result)

        # Global data quality scan
        dq_flags = self._data_quality_scan(rows, columns)

        # Overall pass rate: across all criteria, fraction of applicable checks passed
        total_applicable = sum(r["n_applicable"] for r in results)
        total_pass = sum(r["n_pass"] for r in results)
        overall_pass_rate = round(total_pass / total_applicable, 4) if total_applicable else 0.0

        summary = self._build_summary(results, dq_flags, len(rows), tape_document)

        # Citations: one per criterion (pointing at the tape)
        citations: list[Citation] = [
            Citation(
                source=tape_document,
                location=f"criterion={r['criterion_name']}",
                excerpt=(
                    f"{r['n_pass']}/{r['n_applicable']} pass "
                    f"({r['pass_rate']:.1%})"
                ),
            )
            for r in results
        ]

        confidence = overall_pass_rate if results else 0.5

        return PrimitiveOutput(
            payload={
                "tape_document": tape_document,
                "results": results,
                "overall_pass_rate": overall_pass_rate,
                "data_quality_flags": dq_flags,
                "summary": summary,
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={
                "row_count": len(rows),
                "criteria_checked": len(results),
                "data_quality_flags": len(dq_flags),
            },
        )

    # -----------------------------------------------------------------------
    # Per-criterion check
    # -----------------------------------------------------------------------

    def _check_criterion(
        self,
        crit: dict[str, Any],
        rows: list[dict],
        columns: list[str],
        issues: list[str],
    ) -> Optional[dict[str, Any]]:
        name = str(crit.get("name", "") or "").strip()
        field = str(crit.get("field", "") or "").strip()
        condition = str(crit.get("condition", "") or "").strip().lower()
        threshold = crit.get("threshold")
        segment_field = str(crit.get("segment_field", "") or "").strip()
        segment_value = str(crit.get("segment_value", "") or "").strip()
        description = str(crit.get("description", "") or "").strip()

        if not field or not condition:
            issues.append(f"Criterion {name!r}: missing field or condition.")
            return None
        if field not in columns:
            issues.append(f"Criterion {name!r}: field '{field}' not in tape columns.")
            return None

        n_pass = n_fail = n_missing = 0
        sample_failures: list[dict] = []

        for row in rows:
            # Segment filter
            if segment_field and segment_value:
                seg_val = str(row.get(segment_field, "") or "").strip()
                if seg_val.lower() != segment_value.lower():
                    continue

            raw_val = row.get(field)

            # Missing / unknown
            if raw_val is None or str(raw_val).strip() in ("", "Unknown", "N/A", "NA", "null"):
                n_missing += 1
                continue

            # Evaluate condition
            passed = self._evaluate(condition, raw_val, threshold, issues, name)
            if passed is None:
                n_missing += 1
            elif passed:
                n_pass += 1
            else:
                n_fail += 1
                if len(sample_failures) < 5:
                    sample_failures.append({
                        "loan_id": row.get("loan_id", "?"),
                        "value": raw_val,
                        segment_field: row.get(segment_field) if segment_field else None,
                    })

        n_applicable = n_pass + n_fail
        n_total = n_pass + n_fail + n_missing
        pass_rate = round(n_pass / n_applicable, 4) if n_applicable else 0.0

        return {
            "criterion_name": name,
            "description": description,
            "field": field,
            "condition": condition,
            "threshold": threshold,
            "segment_filter": f"{segment_field}={segment_value}" if segment_field else None,
            "n_total": n_total,
            "n_applicable": n_applicable,
            "n_pass": n_pass,
            "n_fail": n_fail,
            "n_missing": n_missing,
            "pass_rate": pass_rate,
            "sample_failures": sample_failures,
        }

    @staticmethod
    def _evaluate(
        condition: str,
        raw_val: Any,
        threshold: Any,
        issues: list[str],
        name: str,
    ) -> Optional[bool]:
        """Return True/False/None (None = unparseable value)."""
        if condition == "not_null":
            return True  # already checked above

        if condition == "gte_label":
            val_str = str(raw_val).strip().upper()
            thresh_str = str(threshold).strip().upper()
            val_rank = _EPC_RANK.get(val_str)
            thresh_rank = _EPC_RANK.get(thresh_str)
            if val_rank is None or thresh_rank is None:
                return None
            return val_rank <= thresh_rank  # lower rank = better label

        if condition in ("lte_numeric", "gte_numeric"):
            try:
                val_num = float(raw_val)
                thresh_num = float(threshold)
            except (TypeError, ValueError):
                return None
            if math.isnan(val_num):
                return None
            return val_num <= thresh_num if condition == "lte_numeric" else val_num >= thresh_num

        if condition == "equals":
            return str(raw_val).strip().lower() == str(threshold).strip().lower()

        if condition == "in_set":
            allowed = {s.strip().lower() for s in str(threshold).split(",")}
            return str(raw_val).strip().lower() in allowed

        issues.append(f"Criterion {name!r}: unknown condition '{condition}'.")
        return None

    # -----------------------------------------------------------------------
    # Global data quality scan
    # -----------------------------------------------------------------------

    @staticmethod
    def _data_quality_scan(
        rows: list[dict], columns: list[str]
    ) -> list[dict[str, Any]]:
        """Scan the full tape for data quality issues relevant to green analysis."""
        flags: list[dict[str, Any]] = []

        # Check numeric fields for implausible negatives and outliers
        for field in _IMPLAUSIBLE_NEGATIVE_FIELDS:
            if field not in columns:
                continue
            nums = [float(r[field]) for r in rows if _is_number(r.get(field))]
            if not nums:
                continue

            if field == "primary_energy_demand_kwh_m2":
                lo, hi = _PED_PLAUSIBLE_RANGE
                out_of_range = [v for v in nums if v < lo or v > hi]
                negatives = [v for v in nums if v < 0]
                if negatives:
                    flags.append({
                        "field": field,
                        "issue": (
                            f"{len(negatives)} negative values (min={min(negatives):.0f}). "
                            "These may be net-positive-energy buildings or imputation artefacts. "
                            "Verify before applying PED thresholds."
                        ),
                        "count": len(negatives),
                        "sample_values": sorted(negatives)[:5],
                    })
                very_high = [v for v in nums if v > 300]
                if very_high:
                    flags.append({
                        "field": field,
                        "issue": (
                            f"{len(very_high)} values above 300 kWh/m²/year (max={max(very_high):.0f}). "
                            "These likely pre-date modern EPC standards or are data entry errors."
                        ),
                        "count": len(very_high),
                        "sample_values": sorted(very_high, reverse=True)[:5],
                    })

        # Check for unknown/missing EPC labels
        if "epc_label" in columns:
            unknown_epc = sum(
                1 for r in rows
                if str(r.get("epc_label", "") or "").strip().lower() in ("unknown", "", "n/a", "na")
            )
            if unknown_epc:
                flags.append({
                    "field": "epc_label",
                    "issue": (
                        f"{unknown_epc} loans have unknown or missing EPC labels. "
                        "These cannot be verified against green eligibility criteria."
                    ),
                    "count": unknown_epc,
                    "sample_values": [],
                })
            # Check for non-green labels (C, D, E, F, G)
            non_green = [
                r.get("loan_id", "?")
                for r in rows
                if str(r.get("epc_label", "") or "").strip().upper() in ("B", "C", "D", "E", "F", "G")
            ]
            if non_green:
                flags.append({
                    "field": "epc_label",
                    "issue": (
                        f"{len(non_green)} loans have EPC labels below A "
                        f"(B-G), which may not meet green eligibility criteria."
                    ),
                    "count": len(non_green),
                    "sample_values": [str(v) for v in non_green[:5]],
                })

        # Check EPC certificate recency
        if "epc_issue_year" in columns:
            old_certs = [
                r.get("loan_id", "?")
                for r in rows
                if _is_number(r.get("epc_issue_year")) and float(r["epc_issue_year"]) < 2015
            ]
            if old_certs:
                flags.append({
                    "field": "epc_issue_year",
                    "issue": (
                        f"{len(old_certs)} EPC certificates were issued before 2015. "
                        "These may be expired and ineligible under current criteria."
                    ),
                    "count": len(old_certs),
                    "sample_values": [str(v) for v in old_certs[:5]],
                })

        return flags

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_summary(
        results: list[dict],
        dq_flags: list[dict],
        n_rows: int,
        tape_document: str,
    ) -> str:
        lines = [f"Green Eligibility Check — {tape_document} ({n_rows} loans)"]
        for r in results:
            flag = "[PASS]" if r["pass_rate"] >= 0.999 else ("[WARN]" if r["pass_rate"] >= 0.95 else "[FAIL]")
            seg = f" [{r['segment_filter']}]" if r.get("segment_filter") else ""
            lines.append(
                f"  {flag} {r['criterion_name']}{seg}: "
                f"{r['n_pass']:,}/{r['n_applicable']:,} pass "
                f"({r['pass_rate']:.1%})"
                + (f", {r['n_fail']:,} fail" if r["n_fail"] else "")
                + (f", {r['n_missing']:,} missing/unknown" if r["n_missing"] else "")
            )
        if dq_flags:
            lines.append("Data Quality Flags:")
            for f in dq_flags:
                lines.append(f"  [DQ] {f['field']}: {f['issue']}")
        return "\n".join(lines)

    @staticmethod
    def _empty(tape_document: str) -> dict:
        return {
            "tape_document": tape_document,
            "results": [],
            "overall_pass_rate": 0.0,
            "data_quality_flags": [],
            "summary": "No results (no rows provided).",
        }


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
