"""Infer the schema and purpose of an unfamiliar dataset using the LLM.

Given column names and 20 sample rows from any tabular file, this primitive
answers: "What is this data, what does each column mean, and what analyses
would be useful to answer the question?"

This is the first step in the dynamic analysis pipeline:
  connector.auto → extractor.schema_inference → analyzer.code_gen → executor.python

The LLM examines the column names, sample values, data types, and missingness
to produce a structured schema description that downstream code generation can
use to write correct, targeted analysis code.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a data scientist specialising in financial and structured-finance datasets. "
    "You excel at inferring what an unfamiliar dataset represents by examining its "
    "column names, sample values, and data patterns. "
    "Be specific and precise — 'Dutch residential mortgage loan tape' is better than 'financial data'. "
    "Respond with a single JSON object only."
)


class SchemaInferenceExtractor(BasePrimitive):
    """Infer the schema, meaning, and analytical potential of any tabular dataset.

    The output feeds directly into analyzer.code_gen as the 'schema' input,
    giving the code generator the context it needs to write correct Python.
    """

    name = "extractor.schema_inference"
    version = "0.1.0"
    capability = (
        "Infer what an unfamiliar tabular dataset represents using LLM analysis of "
        "column names and sample rows. Returns dataset_type, per-column descriptions "
        "(type, meaning, missing_pct), key_fields relevant to the question, "
        "suggested_analyses, and quality_concerns. "
        "Use after connector.auto when the file format is non-standard. "
        "Output feeds into analyzer.code_gen as the 'schema' input."
    )
    inputs = {
        "columns": "list[str]: column names from connector.auto payload.columns.",
        "sample_rows": "list[dict]: first 20 rows from connector.auto payload.sample_rows.",
        "document": "str: source document name.",
        "question": "str, optional: the analytical question to answer — guides prioritisation.",
    }
    outputs = {
        "payload.document": "str: echoed document name.",
        "payload.dataset_type": "str: what this dataset represents.",
        "payload.columns": "dict: {col_name: {type, description, likely_meaning, missing_pct}}.",
        "payload.key_fields": "list[str]: columns most relevant to the question.",
        "payload.suggested_analyses": "list[str]: useful computations to answer the question.",
        "payload.quality_concerns": "list[str]: data quality issues visible in the sample.",
        "payload.row_count_estimate": "int: row count if determinable from sample.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        columns: list[str] = list(inp.get("columns", []) or [])
        sample_rows: list[dict] = list(inp.get("sample_rows", []) or [])
        document: str = str(inp.get("document", "dataset") or "dataset")
        question: str = str(inp.get("question", "") or "").strip()

        if not columns:
            return PrimitiveOutput(
                payload=self._empty(document),
                citations=[], confidence=0.0, issues=["No columns provided."],
            )

        # Compute per-column missingness from sample
        missing_pcts = _compute_missing_pcts(columns, sample_rows)

        # Compact sample for the prompt (first 5 rows, truncated values)
        compact_sample = _compact_sample(sample_rows[:5], columns)

        question_line = f"\nQUESTION TO ANSWER: {question}\n" if question else ""

        prompt = (
            f"Document: {document}{question_line}\n\n"
            f"COLUMN NAMES ({len(columns)} total):\n{columns}\n\n"
            f"SAMPLE DATA (first {len(sample_rows)} rows):\n{compact_sample}\n\n"
            f"MISSING VALUE RATES (from sample): {missing_pcts}\n\n"
            "TASK: Analyse this dataset and return a JSON object with exactly these fields:\n"
            "{\n"
            '  "dataset_type": str,\n'
            '  "columns": {\n'
            '    "<col_name>": {\n'
            '      "type": "numeric|categorical|date|text|flag|identifier",\n'
            '      "description": str,\n'
            '      "likely_meaning": str,\n'
            '      "missing_pct": float\n'
            "    }\n"
            "  },\n"
            '  "key_fields": list[str],\n'
            '  "suggested_analyses": list[str],\n'
            '  "quality_concerns": list[str]\n'
            "}\n\n"
            "Guidelines:\n"
            "- dataset_type: be specific (e.g. 'Dutch residential RMBS loan tape' not 'financial data')\n"
            "- key_fields: columns most directly relevant to answering the question (if given)\n"
            "- suggested_analyses: concrete pandas operations (e.g. 'df.groupby(\"epc_label\").size()')\n"
            "- quality_concerns: negative values, truncated data, suspicious distributions\n"
            "- Only include columns in 'columns' that exist in the provided column list\n"
        )

        try:
            raw = self._llm(prompt, system=_SYSTEM, max_tokens=3000)
        except Exception as exc:
            return PrimitiveOutput(
                payload=self._empty(document),
                citations=[], confidence=0.0, issues=[f"LLM inference failed: {exc}"],
            )

        if not isinstance(raw, dict):
            return PrimitiveOutput(
                payload=self._empty(document),
                citations=[], confidence=0.0, issues=["Schema inference returned unexpected format."],
            )

        dataset_type = str(raw.get("dataset_type", "unknown dataset")).strip()
        col_schema = raw.get("columns", {}) or {}
        key_fields = [str(f) for f in (raw.get("key_fields", []) or []) if f in columns]
        suggested = [str(s) for s in (raw.get("suggested_analyses", []) or [])[:10]]
        concerns = [str(c) for c in (raw.get("quality_concerns", []) or [])[:8]]

        # Validate col_schema — only keep columns that actually exist
        clean_col_schema = {
            col: col_schema[col] for col in col_schema if col in columns
        }

        confidence = 0.8 if dataset_type != "unknown dataset" else 0.4

        return PrimitiveOutput(
            payload={
                "document": document,
                "dataset_type": dataset_type,
                "columns": clean_col_schema,
                "key_fields": key_fields,
                "suggested_analyses": suggested,
                "quality_concerns": concerns,
                "row_count_estimate": len(sample_rows),
            },
            citations=[Citation(source=document, location="schema", excerpt=dataset_type)],
            confidence=confidence,
            issues=concerns[:3],
            metadata={
                "columns_inferred": len(clean_col_schema),
                "key_fields": key_fields,
            },
        )

    @staticmethod
    def _empty(document: str) -> dict:
        return {
            "document": document,
            "dataset_type": "unknown",
            "columns": {},
            "key_fields": [],
            "suggested_analyses": [],
            "quality_concerns": [],
            "row_count_estimate": 0,
        }


def _compute_missing_pcts(columns: list[str], rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    n = len(rows)
    result = {}
    for col in columns:
        missing = sum(
            1 for r in rows
            if r.get(col) is None or str(r.get(col, "")).strip() in ("", "None", "nan", "NaN", "N/A")
        )
        if missing:
            result[col] = round(missing / n, 2)
    return result


def _compact_sample(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "(no sample rows)"
    lines = []
    for row in rows:
        compact = {col: str(row.get(col, ""))[:30] for col in columns[:20]}
        lines.append(json.dumps(compact))
    return "\n".join(lines)
