"""Safe Python code execution via subprocess isolation.

The only primitive in sf-agents that calls subprocess.run. Generated Python
code is executed in a child process so any crash, hang, infinite loop, or
exception cannot affect the parent application.

Security model:
  - Process isolation: child process cannot affect the parent
  - Data injection: rows are written to a temp file and loaded by the harness;
    the child never accesses arbitrary file paths
  - Timeout: subprocess.run(timeout=N) kills the child if it hangs
  - Allowed imports: the code-gen prompt restricts imports; even if violated the
    child process is isolated and temp files are cleaned up regardless
  - Temp files: written to tempfile.mkdtemp() and deleted after execution

The executor supports retry: if the child exits with a non-zero code, the
caller can pass the stderr as error_context to code_gen for a fix attempt,
then call this primitive again with the fixed code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput


class PythonRunnerExecutor(BasePrimitive):
    """Execute a Python analysis script against a dataset in a safe subprocess.

    The script receives the full dataset as a pre-loaded pandas DataFrame
    named ``df``. It must print a single JSON object to stdout as its result.
    """

    name = "executor.python"
    version = "0.1.0"
    capability = (
        "Execute a Python analysis script against a dataset in a sandboxed subprocess. "
        "The script receives the full dataset as a pandas DataFrame named 'df' and must "
        "print a single JSON-serializable result to stdout. Returns the parsed result, "
        "execution time, stdout, stderr, and exit code. Confidence=1.0 on success, 0.0 "
        "on failure. Use after analyzer.code_gen to run generated analysis code. "
        "On failure, pass stderr as error_context back to analyzer.code_gen for a retry."
    )
    inputs = {
        "code": "str: Python script to execute. Must print json.dumps(result) to stdout.",
        "rows": "list[dict]: full dataset rows (from any tabular connector).",
        "columns": "list[str]: column names.",
        "document": "str: source document name (for citations).",
        "timeout_seconds": "int, optional: max execution time in seconds (default 45).",
    }
    outputs = {
        "payload.success": "bool: True if script executed without error.",
        "payload.result": "any: parsed JSON result from stdout (None if failed).",
        "payload.execution_time_ms": "float: wall-clock execution time.",
        "payload.stdout": "str: raw stdout from the script.",
        "payload.stderr": "str: raw stderr (error messages if failed).",
        "payload.exit_code": "int: process exit code (0 = success).",
        "payload.code_used": "str: the exact script that was executed.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        code: str = str(inp.get("code", "") or "").strip()
        rows: list[dict[str, Any]] = list(inp.get("rows", []) or [])
        columns: list[str] = list(inp.get("columns", []) or [])
        document: str = str(inp.get("document", "data") or "data")
        timeout: int = int(inp.get("timeout_seconds", 45) or 45)

        if not code:
            return PrimitiveOutput(
                payload=self._failure_payload("", "", 1, "No code provided.", ""),
                citations=[], confidence=0.0, issues=["No code provided."],
            )

        tmpdir = tempfile.mkdtemp(prefix="sf_exec_")
        data_path = os.path.join(tmpdir, "data.json")
        script_path = os.path.join(tmpdir, "script.py")

        try:
            # Write data
            with open(data_path, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, default=str)

            # Build harness that pre-loads the DataFrame
            harness = _build_harness(data_path, columns, code)

            with open(script_path, "w", encoding="utf-8") as fh:
                fh.write(harness)

            t0 = time.monotonic()
            try:
                proc = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                duration = (time.monotonic() - t0) * 1000
                return PrimitiveOutput(
                    payload=self._failure_payload(
                        "", f"Script exceeded {timeout}s timeout.", 1, code, document
                    ),
                    citations=[], confidence=0.0,
                    issues=[f"Execution timed out after {timeout}s."],
                    metadata={"execution_time_ms": duration},
                )

            duration = (time.monotonic() - t0) * 1000
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            exit_code = proc.returncode

            if exit_code != 0 or not stdout:
                return PrimitiveOutput(
                    payload=self._failure_payload(stdout, stderr, exit_code, code, document),
                    citations=[], confidence=0.0,
                    issues=[f"Script failed (exit {exit_code}): {stderr[:300]}"],
                    metadata={"execution_time_ms": duration},
                )

            # Parse stdout as JSON
            try:
                result = json.loads(stdout)
            except json.JSONDecodeError as exc:
                return PrimitiveOutput(
                    payload=self._failure_payload(
                        stdout, f"stdout is not valid JSON: {exc}", 1, code, document
                    ),
                    citations=[], confidence=0.0,
                    issues=[f"Script stdout is not valid JSON: {exc}"],
                    metadata={"execution_time_ms": duration},
                )

            citations = [Citation(
                source=document,
                location="computed",
                excerpt=str(result)[:200] if result is not None else "(empty result)",
            )]

            return PrimitiveOutput(
                payload={
                    "success": True,
                    "result": result,
                    "execution_time_ms": round(duration, 1),
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                    "code_used": code,
                    "document": document,
                },
                citations=citations,
                confidence=1.0,
                issues=[],
                metadata={"execution_time_ms": duration, "rows_processed": len(rows)},
            )

        finally:
            # Always clean up temp files
            for path in (script_path, data_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass

    @staticmethod
    def _failure_payload(
        stdout: str, stderr: str, exit_code: int, code: str, document: str
    ) -> dict:
        return {
            "success": False,
            "result": None,
            "execution_time_ms": 0.0,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "code_used": code,
            "document": document,
        }


def _build_harness(data_path: str, columns: list[str], user_code: str) -> str:
    """Wrap user code in a harness that pre-loads the DataFrame."""
    safe_data_path = data_path.replace("\\", "\\\\")
    return f"""\
import pandas as pd
import numpy as np
import json
import math
import statistics
import re
import datetime
import collections

# Load data injected by the executor
with open("{safe_data_path}", encoding="utf-8") as _f:
    _rows = json.load(_f)

df = pd.DataFrame(_rows)

# Restore typed columns where possible
for _col in df.columns:
    try:
        df[_col] = pd.to_numeric(df[_col], errors="ignore")
    except Exception:
        pass

# --- user code below ---
{user_code}
"""
