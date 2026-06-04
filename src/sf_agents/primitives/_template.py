"""Primitive template — copy this file to implement a new primitive.

Step-by-step guide:
  1. Copy this file to the right subdirectory:
       connectors/ — for data loaders (PDF, CSV, API, tape)
       extractors/ — for LLM-backed information extraction
       analyzers/  — for reasoning/comparison (may use LLM)
       validators/ — for schema/rule checking (no LLM, deterministic)

  2. Rename the class, set the class attributes (name, version, capability,
     inputs, outputs).

  3. Implement run(inp) to produce a PrimitiveOutput.

  4. Register in src/sf_agents/orchestrator/registry.py:
       registry.register(lambda hook: MyPrimitive(audit_hook=hook))
       # For LLM-backed primitives:
       registry.register(lambda hook: MyPrimitive(llm=llm, audit_hook=hook))

  5. Write a test in tests/test_<name>.py that works fully offline
     (use mock_llm from conftest, or no LLM if deterministic).

IMPORTANT RULES
---------------
  - Citations are mandatory for any claim. Populate citations with real
    source/location/excerpt triples — do NOT leave them empty.
  - confidence must reflect real coverage: 0.0 = no useful output,
    1.0 = fully verifiable.
  - Never call the LLM directly. Inject it via __init__ and call self._llm().
  - Only _llm.py knows about AWS Bedrock. New primitives use self._llm(prompt).
  - Tests must not require network access. Use mock_llm from conftest.py.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

# Type alias for the injectable JSON-LLM callable
JsonLLM = Callable[..., Any]

# System prompt shown to the LLM (omit for non-LLM primitives)
_SYSTEM = (
    "You are a structured-finance analyst. "
    "Replace this with a domain-specific instruction."
)


class MyNewPrimitive(BasePrimitive):
    """One-line description of what this primitive does.

    Input args:
        my_required_arg (str): Description of what this is.
        my_optional_arg (int, optional): Description. Defaults to 42.

    Payload:
        ``{"result_key": <value>, ...}``
    """

    # ── Required class attributes ─────────────────────────────────────────── #
    name = "category.my_new_primitive"   # e.g. "connector.esma_tape"
    version = "0.1.0"
    capability = (
        "One precise sentence describing what this primitive does and when to use it. "
        "The planner reads this to decide whether to include it in a plan."
    )
    inputs = {
        "my_required_arg": "str: description of what this input is and where to get it.",
        "my_optional_arg": "int, optional: description (default: 42).",
    }
    outputs = {
        "payload.result_key": "type: description of what this field contains.",
    }

    # ── Constructor ──────────────────────────────────────────────────────── #
    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        # Remove llm if this is a deterministic (non-LLM) primitive.
        if llm is None:
            from ._llm import complete_json as llm
        self._llm = llm

    # ── Core logic ───────────────────────────────────────────────────────── #
    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        # 1. Read inputs
        my_arg: str = inp.get("my_required_arg", "")
        my_opt: int = int(inp.get("my_optional_arg", 42))

        # 2. Do work (deterministic processing or LLM call)
        #    For LLM calls:
        #      raw = self._llm(prompt, system=_SYSTEM, max_tokens=1024)
        #      records = raw if isinstance(raw, list) else []
        result = {"result_key": f"processed: {my_arg}"}

        # 3. Build citations — REQUIRED for every claim made
        #    - source: the document or file name (e.g. "prospectus.pdf")
        #    - location: "page=42" for PDFs, "row=17" for tabular data
        #    - excerpt: verbatim text from the source (never invented)
        citations = [
            Citation(
                source="source_document.pdf",
                location="page=1",
                excerpt="verbatim text from page 1",
            )
        ]

        # 4. Compute confidence honestly
        #    0.0 = no usable output; 1.0 = fully verified output
        confidence = 1.0

        # 5. Collect non-fatal warnings in issues (NOT exceptions)
        issues: list[str] = []
        if not my_arg:
            issues.append("my_required_arg was empty; result may be incomplete.")
            confidence = 0.0

        return PrimitiveOutput(
            payload=result,
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={"my_opt": my_opt},  # any extra diagnostic info
        )
