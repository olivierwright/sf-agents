"""Rule-based validator for the ESMA-style RMBS loan-tape field subset.

The expected field set below is derived from the ACTUAL columns present in the
Green Lion 2026-1 synthetic tapes shipped in this repository -- not a guessed or
idealised ESMA template. We validate a focused subset that matters for the
definition-transparency use case (identity, performing status, arrears and
default fields), plus light value-domain checks on those fields.

This primitive is deterministic (no LLM) so it is fully testable offline.
"""

from __future__ import annotations

from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

#: Fields that must be present. Sourced from the real tape header.
REQUIRED_FIELDS: tuple[str, ...] = (
    "loan_id",
    "transaction_name",
    "reporting_date",
    "current_balance",
    "performing_status",
    "arrears_bucket",
    "arrears_amount",
    "days_past_due",
    "default_crr_flag",
    "foreclosure_flag",
    "forbearance_flag",
    "restructuring_flag",
)

#: Y/N flag fields whose values must be in {"Y", "N"}.
YN_FLAG_FIELDS: tuple[str, ...] = (
    "default_crr_flag",
    "foreclosure_flag",
    "forbearance_flag",
    "restructuring_flag",
)

#: Non-negative numeric fields.
NON_NEGATIVE_FIELDS: tuple[str, ...] = ("current_balance", "arrears_amount", "days_past_due")


class EsmaSchemaValidator(BasePrimitive):
    """Validate a loan tape against the required ESMA-subset schema and domains.

    Input args:
        columns (list[str]): The tape's column names (from the connector).
        rows (list[dict]): The tape's row records.
        document (str, optional): Source name for citations.

    Payload:
        ``{"ok": bool, "missing_fields": [...], "checks": {...},
           "violations": [...]}``
    """

    name = "validator.esma_schema"
    version = "0.1.0"
    capability = (
        "Validate a loan tape against the required ESMA-style RMBS field subset "
        "(identity, performing status, arrears and default fields) and check "
        "basic value domains (Y/N flags, non-negative amounts). Rule-based; no LLM."
    )
    inputs = {
        "columns": "list[str]: reference the loan tape connector's payload.columns.",
        "rows": "list[dict]: reference the loan tape connector's payload.rows.",
        "document": "str, optional: source name; reference the connector's payload.document.",
    }
    outputs = {
        "payload.ok": "bool: whether all required fields are present and domains hold.",
        "payload.missing_fields": "list[str]: required fields absent from the tape.",
        "payload.checks": "dict: counts (required_fields, present_required, rows_checked).",
        "payload.violations": "list[str]: value-domain violations found.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        columns: list[str] = list(inp.get("columns", []) or [])
        rows: list[dict[str, Any]] = list(inp.get("rows", []) or [])
        document: str = inp.get("document", "loan_tape")

        present = set(columns)
        missing = [f for f in REQUIRED_FIELDS if f not in present]
        violations: list[str] = []

        # Value-domain checks only run on fields that exist.
        for field in YN_FLAG_FIELDS:
            if field in present:
                bad = self._first_bad_flag(rows, field)
                if bad is not None:
                    idx, value = bad
                    violations.append(
                        f"row {idx}: {field}={value!r} is not a Y/N flag."
                    )
        for field in NON_NEGATIVE_FIELDS:
            if field in present:
                bad = self._first_negative(rows, field)
                if bad is not None:
                    idx, value = bad
                    violations.append(
                        f"row {idx}: {field}={value!r} is negative."
                    )

        # Confidence: fraction of required fields present, lightly penalised by
        # any value-domain violations found.
        present_required = len(REQUIRED_FIELDS) - len(missing)
        base = present_required / len(REQUIRED_FIELDS)
        penalty = min(0.3, 0.05 * len(violations))
        confidence = round(max(0.0, base - penalty), 4)
        ok = not missing and not violations

        issues: list[str] = []
        if missing:
            issues.append(f"Missing required fields: {', '.join(missing)}.")
        issues.extend(violations)

        citations: list[Citation] = []
        if rows:
            citations.append(
                Citation(
                    source=document,
                    location="row=0",
                    excerpt="schema validated against required ESMA field subset",
                )
            )

        return PrimitiveOutput(
            payload={
                "ok": ok,
                "missing_fields": missing,
                "checks": {
                    "required_fields": len(REQUIRED_FIELDS),
                    "present_required": present_required,
                    "rows_checked": len(rows),
                },
                "violations": violations,
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={"document": document},
        )

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _first_bad_flag(rows: list[dict[str, Any]], field: str):
        for idx, row in enumerate(rows):
            value = row.get(field)
            if value is None:
                continue
            if str(value).strip().upper() not in {"Y", "N"}:
                return idx, value
        return None

    @staticmethod
    def _first_negative(rows: list[dict[str, Any]], field: str):
        for idx, row in enumerate(rows):
            value = row.get(field)
            if value is None:
                continue
            try:
                if float(value) < 0:
                    return idx, value
            except (TypeError, ValueError):
                return idx, value
        return None
