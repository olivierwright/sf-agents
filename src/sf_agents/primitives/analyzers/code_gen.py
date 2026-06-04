"""LLM-based Python analysis code generator.

Given a question, an inferred dataset schema, and sample rows, generates a
Python script that computes the answer deterministically against the full
dataset. The generated script receives the data as a pre-loaded pandas
DataFrame named ``df`` and must print a single JSON-serializable result.

Usage pattern:
  extractor.schema_inference → analyzer.code_gen → executor.python

On failure, executor.python returns the stderr. Pass it as error_context to
this primitive to regenerate a fixed script.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are an expert Python data analyst. You write clean, efficient pandas code "
    "to answer structured-finance analysis questions. "
    "You always handle missing values (NaN, None) gracefully. "
    "You always produce JSON-serializable output (use .tolist(), .to_dict(), str() as needed). "
    "You write ONLY the Python script — no explanation, no markdown fences, no comments "
    "unless they clarify non-obvious logic."
)

# Allowed imports that can be safely used in generated code
_ALLOWED_IMPORTS = (
    "pandas (as pd), numpy (as np), json, math, statistics, "
    "re, datetime, collections, itertools"
)


class CodeGenAnalyzer(BasePrimitive):
    """Generate a Python analysis script tailored to a question and dataset schema.

    The generated script runs against the full dataset via executor.python.
    On failure, pass the error back as error_context to get a corrected script.
    """

    name = "analyzer.code_gen"
    version = "0.1.0"
    capability = (
        "Generate a Python analysis script that answers a question about a dataset. "
        "Takes a question, dataset schema (from extractor.schema_inference), and sample rows. "
        "The generated script receives a pre-loaded pandas DataFrame named 'df' and must "
        "print json.dumps(result) to stdout. Pass error_context (stderr from a failed run) "
        "to regenerate a fixed version. Output feeds into executor.python."
    )
    inputs = {
        "question": "str: the analytical question the code must answer.",
        "schema": "dict: dataset schema from extractor.schema_inference payload.",
        "sample_rows": "list[dict]: 5-10 sample rows for context.",
        "document": "str: source document name.",
        "context": "str, optional: additional domain context.",
        "error_context": "str, optional: stderr from a failed executor.python run — triggers code fix.",
    }
    outputs = {
        "payload.code": "str: the generated Python script.",
        "payload.expected_output_description": "str: what the script is expected to return.",
        "payload.column_references": "list[str]: tape columns the code uses.",
        "payload.document": "str: echoed document name.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        question: str = str(inp.get("question", "") or "").strip()
        schema: dict = inp.get("schema", {}) or {}
        sample_rows: list[dict] = list(inp.get("sample_rows", []) or [])[:8]
        document: str = str(inp.get("document", "dataset") or "dataset")
        context: str = str(inp.get("context", "") or "").strip()
        error_context: str = str(inp.get("error_context", "") or "").strip()

        if not question:
            return PrimitiveOutput(
                payload={"code": "", "expected_output_description": "", "column_references": [], "document": document},
                citations=[], confidence=0.0, issues=["question is required."],
            )

        dataset_type = str(schema.get("dataset_type", "unknown dataset"))
        col_schema = schema.get("columns", {}) or {}
        key_fields = schema.get("key_fields", []) or []
        suggested = schema.get("suggested_analyses", []) or []

        # Compact column schema for the prompt
        col_desc = _format_column_schema(col_schema)
        sample_text = json.dumps(sample_rows[:5], default=str, indent=2)[:1500]
        context_line = f"\nCONTEXT: {context}\n" if context else ""
        suggested_line = (
            f"\nSUGGESTED APPROACHES: {', '.join(suggested[:4])}\n" if suggested else ""
        )
        key_fields_line = f"\nKEY FIELDS: {key_fields}\n" if key_fields else ""

        # Retry mode: include the error and the broken code
        if error_context:
            error_section = (
                f"\n\nPREVIOUS ATTEMPT FAILED WITH THIS ERROR:\n{error_context[:800]}\n\n"
                "Fix the script. The error is typically: wrong column name, wrong data type, "
                "unhandled NaN, or non-serializable result. Return ONLY the corrected script."
            )
        else:
            error_section = ""

        prompt = (
            f"DATASET: {dataset_type} — from '{document}'\n"
            f"QUESTION: {question}\n"
            f"{context_line}"
            f"{key_fields_line}"
            f"{suggested_line}\n"
            f"COLUMN SCHEMA:\n{col_desc}\n\n"
            f"SAMPLE DATA (first {len(sample_rows)} rows):\n{sample_text}\n\n"
            "TASK: Write a Python script that answers the question above.\n\n"
            "RULES:\n"
            f"- Allowed imports: {_ALLOWED_IMPORTS}\n"
            "- The full dataset is available as a pandas DataFrame called `df`\n"
            "  (already loaded — do NOT read any files)\n"
            "- The script MUST end with: print(json.dumps(result))\n"
            "- result must be JSON-serializable: use .tolist(), .to_dict(), str(), float(), int()\n"
            "  for numpy types. Never leave numpy int64/float64 in the output.\n"
            "- Handle missing values: use .fillna(), .dropna(), or explicit None checks\n"
            "- Be efficient: avoid row-by-row Python loops on large DataFrames\n"
            "- Return a dict with descriptive keys that clearly label each result\n"
            "- Do NOT use: os, sys, subprocess, requests, urllib, socket, open(), eval(), exec()\n\n"
            "Write ONLY the Python script. No explanation. No markdown."
            f"{error_section}"
        )

        try:
            from .._llm import complete
            raw_code = complete(prompt, system=_SYSTEM, max_tokens=2000, temperature=0.1).strip()
        except Exception as exc:
            return PrimitiveOutput(
                payload={"code": "", "expected_output_description": "", "column_references": [], "document": document},
                citations=[], confidence=0.0, issues=[f"Code generation failed: {exc}"],
            )

        # Strip any accidental markdown fences
        raw_code = _strip_fences(raw_code)

        # Extract column references from the code
        col_refs = [col for col in col_schema if col in raw_code]

        # Generate expected output description
        expected_desc = (
            f"JSON result answering: '{question[:100]}' "
            f"using fields: {col_refs[:6]}"
        )

        return PrimitiveOutput(
            payload={
                "code": raw_code,
                "expected_output_description": expected_desc,
                "column_references": col_refs,
                "document": document,
            },
            citations=[Citation(source=document, location="generated_code", excerpt=raw_code[:200])],
            confidence=0.85 if raw_code else 0.0,
            issues=[] if raw_code else ["Empty code generated."],
            metadata={"code_length": len(raw_code), "column_refs": len(col_refs)},
        )


def _format_column_schema(col_schema: dict) -> str:
    if not col_schema:
        return "(no schema available)"
    lines = []
    for col, info in list(col_schema.items())[:40]:
        if not isinstance(info, dict):
            lines.append(f"  {col}: unknown")
            continue
        col_type = info.get("type", "?")
        desc = info.get("description", "") or info.get("likely_meaning", "")
        missing = info.get("missing_pct", 0)
        line = f"  {col} ({col_type}): {desc[:60]}"
        if missing:
            line += f" [missing: {missing:.0%}]"
        lines.append(line)
    return "\n".join(lines)


def _strip_fences(code: str) -> str:
    if "```" not in code:
        return code
    lines = code.splitlines()
    result = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not (not in_fence and stripped.startswith("```")):
            result.append(line)
    return "\n".join(result).strip()
