"""Autonomous dynamic data analysis loop.

Wraps schema inference → code generation → execution → retry into a single
primitive. The planner can drop this in for any "analyse this unknown data"
question — it handles the full pipeline internally.

Loop phases (stops at first success):
  1. Schema inference  — LLM understands the dataset
  2. Code generation   — LLM writes pandas analysis code
  3. Execution         — subprocess runs the code against the full dataset
  4. Error retry       — if execution fails, regenerate code with error feedback
     (up to max_retries attempts)
  5. Result sanity     — LLM checks whether the result is a plausible answer
  6. Regeneration      — if result is implausible, one more attempt with feedback

This mirrors how a human analyst works: understand the data, write a formula,
run it, fix errors, check the result makes sense.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput
from .code_gen import CodeGenAnalyzer
from ..extractors.schema_inference import SchemaInferenceExtractor
from ..executors.python_runner import PythonRunnerExecutor

logger = logging.getLogger("sf_agents.analyzer.dynamic")

JsonLLM = Callable[..., Any]

_SYSTEM_VERIFY = (
    "You are a data analyst reviewing a computed result. "
    "Determine whether the result is a plausible, meaningful answer to the question. "
    "Be pragmatic — partial results that contain useful data are acceptable. "
    "Respond with a single JSON object only."
)


class DynamicAnalyzer(BasePrimitive):
    """Autonomous analysis loop: infer schema → generate code → run → retry.

    Handles any tabular dataset without requiring domain-specific primitives.
    Best for unfamiliar files or questions that need custom computation.
    """

    name = "analyzer.dynamic"
    version = "0.1.0"
    capability = (
        "Autonomously analyse any tabular dataset to answer a question. "
        "Infers the dataset schema, generates Python analysis code, executes it "
        "in a safe subprocess, and retries with error feedback if execution fails. "
        "Returns the computed answer, inferred schema, the code used, attempt count, "
        "and execution log. Use when no domain-specific primitive covers the question, "
        "especially for unfamiliar file formats or custom computations. "
        "Input columns/rows from connector.auto or any tabular connector."
    )
    inputs = {
        "question": "str: the analytical question to answer.",
        "columns": "list[str]: column names from any tabular connector.",
        "rows": "list[dict]: full dataset rows.",
        "document": "str: source document name.",
        "context": "str, optional: domain context to guide analysis.",
        "max_retries": "int, optional: max code-fix attempts on failure (default 3).",
        "timeout_seconds": "int, optional: per-execution timeout (default 45).",
    }
    outputs = {
        "payload.question": "str: echoed question.",
        "payload.answer": "any: the computed JSON result.",
        "payload.schema": "dict: inferred dataset schema.",
        "payload.code_used": "str: the final Python script that succeeded.",
        "payload.attempts": "int: number of execution attempts made.",
        "payload.execution_log": "list[str]: per-attempt outcome messages.",
        "payload.document": "str: echoed document name.",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as _json_llm
            from .._llm import complete as _text_llm
        else:
            _json_llm = llm
            _text_llm = llm
        self._json_llm = _json_llm
        self._text_llm = _text_llm

        # Reuse the standalone primitives internally
        self._schema_extractor = SchemaInferenceExtractor(llm=_json_llm)
        self._code_gen = CodeGenAnalyzer(llm=None)  # uses complete() directly
        self._runner = PythonRunnerExecutor()

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        question: str = str(inp.get("question", "") or "").strip()
        columns: list[str] = list(inp.get("columns", []) or [])
        rows: list[dict[str, Any]] = list(inp.get("rows", []) or [])
        document: str = str(inp.get("document", "dataset") or "dataset")
        context: str = str(inp.get("context", "") or "").strip()
        max_retries: int = int(inp.get("max_retries", 3) or 3)
        timeout: int = int(inp.get("timeout_seconds", 45) or 45)

        if not question:
            return self._failure("question is required.", {}, document, [], 0)
        if not rows:
            return self._failure("No data rows provided.", {}, document, [], 0)

        sample_rows = rows[:20]
        execution_log: list[str] = []

        # ------------------------------------------------------------------
        # Phase 1: Schema inference
        # ------------------------------------------------------------------
        schema_out = self._schema_extractor(
            PrimitiveInput(args={
                "columns": columns,
                "sample_rows": sample_rows,
                "document": document,
                "question": question,
            }),
            run_id="dynamic", step_id="schema_inference",
        )
        schema = schema_out.payload if isinstance(schema_out.payload, dict) else {}
        dataset_type = schema.get("dataset_type", "unknown")
        execution_log.append(f"Schema inferred: {dataset_type}")

        # ------------------------------------------------------------------
        # Phase 2+: Code generation and execution loop
        # ------------------------------------------------------------------
        error_context = ""
        last_code = ""
        answer = None

        for attempt in range(1, max_retries + 1):
            # Generate (or fix) the analysis code
            code_inp = PrimitiveInput(args={
                "question": question,
                "schema": schema,
                "sample_rows": sample_rows[:5],
                "document": document,
                "context": context,
                "error_context": error_context,
            })
            code_out = self._code_gen(code_inp, run_id="dynamic", step_id=f"code_gen_{attempt}")
            code = str(code_out.payload.get("code", "") if isinstance(code_out.payload, dict) else "")

            if not code:
                execution_log.append(f"Attempt {attempt}: code generation produced empty script.")
                error_context = "The code generator returned an empty script. Please generate a valid Python script."
                continue

            last_code = code

            # Execute
            exec_inp = PrimitiveInput(args={
                "code": code,
                "rows": rows,
                "columns": columns,
                "document": document,
                "timeout_seconds": timeout,
            })
            exec_out = self._runner(exec_inp, run_id="dynamic", step_id=f"exec_{attempt}")
            exec_payload = exec_out.payload if isinstance(exec_out.payload, dict) else {}

            if exec_payload.get("success"):
                answer = exec_payload.get("result")
                execution_log.append(
                    f"Attempt {attempt}: success "
                    f"({exec_payload.get('execution_time_ms', 0):.0f}ms)"
                )

                # Phase 5: sanity check
                if answer is not None:
                    ok, note = self._verify_result(question, answer, schema)
                    if ok:
                        execution_log.append(f"Verification: passed — {note}")
                        break
                    else:
                        execution_log.append(f"Verification: result seems wrong — {note}")
                        error_context = (
                            f"The script ran successfully but the result seems incorrect: {note}. "
                            f"Result was: {str(answer)[:200]}. "
                            "Please rewrite the script to compute the correct answer."
                        )
                        answer = None  # force retry
                        continue
                break  # success even with null answer
            else:
                stderr = exec_payload.get("stderr", "") or ""
                stdout = exec_payload.get("stdout", "") or ""
                execution_log.append(
                    f"Attempt {attempt}: failed (exit {exec_payload.get('exit_code', '?')}): "
                    f"{stderr[:200]}"
                )
                error_context = stderr or stdout or "Script failed with unknown error."

        confidence = self._compute_confidence(answer, attempt, schema)

        return PrimitiveOutput(
            payload={
                "question": question,
                "answer": answer,
                "schema": schema,
                "code_used": last_code,
                "attempts": attempt,
                "execution_log": execution_log,
                "document": document,
            },
            citations=[Citation(
                source=document,
                location="dynamic_analysis",
                excerpt=str(answer)[:200] if answer else "(no result)",
            )],
            confidence=confidence,
            issues=[] if answer is not None else ["Dynamic analysis did not produce a result."],
            metadata={
                "attempts": attempt,
                "dataset_type": dataset_type,
                "rows_analysed": len(rows),
            },
        )

    def _verify_result(
        self, question: str, result: Any, schema: dict
    ) -> tuple[bool, str]:
        """Ask the LLM whether the result is a plausible answer to the question."""
        import json
        result_text = json.dumps(result, default=str)[:500]
        dataset_type = schema.get("dataset_type", "dataset")
        prompt = (
            f"QUESTION: {question}\n"
            f"DATASET TYPE: {dataset_type}\n"
            f"COMPUTED RESULT: {result_text}\n\n"
            "Is this result a plausible, meaningful answer to the question above? "
            "Consider: are the data types sensible? Are the values in a reasonable range? "
            "Does it directly address what was asked?\n\n"
            'Return JSON: {"valid": bool, "confidence": float, "note": str}'
        )
        try:
            raw = self._json_llm(prompt, system=_SYSTEM_VERIFY, max_tokens=200)
            if isinstance(raw, dict):
                return bool(raw.get("valid", True)), str(raw.get("note", ""))
        except Exception as exc:
            logger.debug("Verification LLM call failed: %s", exc)
        return True, "verification skipped"

    @staticmethod
    def _compute_confidence(answer: Any, attempts: int, schema: dict) -> float:
        if answer is None:
            return 0.0
        base = 0.9
        # Penalise for multiple attempts
        attempt_penalty = (attempts - 1) * 0.05
        # Penalise for unknown schema
        schema_penalty = 0.1 if schema.get("dataset_type", "unknown") == "unknown" else 0.0
        return max(0.0, round(base - attempt_penalty - schema_penalty, 4))

    @staticmethod
    def _failure(
        issue: str,
        schema: dict,
        document: str,
        log: list[str],
        attempts: int,
    ) -> PrimitiveOutput:
        return PrimitiveOutput(
            payload={
                "question": "",
                "answer": None,
                "schema": schema,
                "code_used": "",
                "attempts": attempts,
                "execution_log": log + [issue],
                "document": document,
            },
            citations=[],
            confidence=0.0,
            issues=[issue],
        )
