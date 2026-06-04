"""The planner: question + registry -> an inspectable JSON DAG.

The planner asks the LLM to compose *only* registered primitives into a directed
acyclic graph of steps. Each step names a primitive, supplies literal args, and
may reference an upstream step's output via a reference object
``{"$from": "<step_id>", "path": "payload.pages"}``.

Planner-first is the default and the demo's strongest moment: a live, readable
plan grounded in the real capability catalogue. A deterministic ``fallback`` plan
is used *only* when the LLM is unavailable or returns something invalid, and the
chosen path is logged so it is always obvious which one ran.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .registry import Registry

logger = logging.getLogger("sf_agents.planner")

JsonLLM = Callable[..., Any]

_SYSTEM = (
    "You are a planning engine for a structured-finance analysis framework. "
    "You compose registered primitives into a directed acyclic graph (DAG). "
    "You may ONLY use primitives from the provided catalogue. Never invent "
    "primitive names or arguments.\n\n"
    "CONNECTOR SELECTION RULES — follow strictly:\n"
    "- connector.prospectus: only for the 'prospectus' document (PDF).\n"
    "- connector.investor_report: only for 'investor_report' documents (PDF).\n"
    "- connector.pdf_document: for any other PDF document.\n"
    "- connector.loan_tape: ONLY for CSV/XLSX files (the loan tape). Never pass a PDF.\n"
    "- connector.remittance_file: ONLY if a CSV/XLSX remittance file is explicitly "
    "listed in context.documents. If no such file exists in context, DO NOT include "
    "connector.remittance_file in the plan.\n"
    "- validator.esma_schema: use AFTER connector.loan_tape, not after PDF connectors.\n"
    "Always check context.document_formats and context.connector_guide before selecting connectors."
)


@dataclass(frozen=True)
class Step:
    """A single node in the plan DAG."""

    step_id: str
    primitive: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "primitive": self.primitive,
            "args": self.args,
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class Plan:
    """An ordered, validated DAG plus the explanation and provenance."""

    steps: list[Step]
    explanation: str = ""
    source: str = "planner"  # "planner" or "fallback"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "explanation": self.explanation,
            "steps": [s.as_dict() for s in self.steps],
        }


class PlanValidationError(ValueError):
    """Raised when a candidate plan is structurally invalid."""


class Planner:
    """Build an executable :class:`Plan` from a question and a registry."""

    def __init__(self, llm: Optional[JsonLLM] = None) -> None:
        if llm is None:
            from ..primitives._llm import complete_json as llm
        self._llm = llm

    def plan(
        self,
        question: str,
        registry: Registry,
        *,
        context: Optional[dict[str, Any]] = None,
        fallback: Optional[Plan] = None,
    ) -> Plan:
        """Return a validated plan, preferring the LLM and falling back if needed.

        Args:
            question: The natural-language question to answer.
            registry: The catalogue the plan may draw from.
            context: Optional hints (e.g. known document paths, terms) the LLM
                may reference when filling step args.
            fallback: A deterministic plan used only if the LLM path fails.

        Returns:
            A :class:`Plan`. ``plan.source`` records which path produced it.
        """
        try:
            raw = self._llm(
                self._build_prompt(question, registry, context),
                system=_SYSTEM,
                max_tokens=8000,
            )
            plan = self._parse(raw)
            self.validate(plan, registry)
            logger.info("planner: using LLM-generated plan (%d steps)", len(plan.steps))
            return plan
        except Exception as exc:  # noqa: BLE001 - any failure routes to fallback
            if fallback is None:
                raise
            logger.warning(
                "planner: LLM plan unavailable/invalid (%s); using deterministic fallback",
                exc,
            )
            self.validate(fallback, registry)
            return fallback

    # -- validation -------------------------------------------------------- #
    @staticmethod
    def validate(plan: Plan, registry: Registry) -> None:
        """Validate names, references and acyclicity. Raises on any problem."""
        if not plan.steps:
            raise PlanValidationError("Plan has no steps.")
        seen: set[str] = set()
        for step in plan.steps:
            if step.step_id in seen:
                raise PlanValidationError(f"Duplicate step_id: {step.step_id!r}")
            seen.add(step.step_id)
            if step.primitive not in registry:
                raise PlanValidationError(
                    f"Step {step.step_id!r} uses unknown primitive {step.primitive!r}"
                )
        ids = {s.step_id for s in plan.steps}
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in ids:
                    raise PlanValidationError(
                        f"Step {step.step_id!r} depends on unknown step {dep!r}"
                    )
            for ref in _iter_refs(step.args):
                if ref not in ids:
                    raise PlanValidationError(
                        f"Step {step.step_id!r} references unknown step {ref!r}"
                    )
        Planner.topological_order(plan)  # raises on cycle

    @staticmethod
    def topological_order(plan: Plan) -> list[Step]:
        """Return steps in dependency order (edges from depends_on + arg refs).

        Raises:
            PlanValidationError: If the graph contains a cycle.
        """
        by_id = {s.step_id: s for s in plan.steps}
        deps: dict[str, set[str]] = {}
        for step in plan.steps:
            edges = set(step.depends_on) | set(_iter_refs(step.args))
            deps[step.step_id] = edges
        ordered: list[Step] = []
        resolved: set[str] = set()
        while len(resolved) < len(by_id):
            progressed = False
            for sid, edges in deps.items():
                if sid in resolved:
                    continue
                if edges <= resolved:
                    ordered.append(by_id[sid])
                    resolved.add(sid)
                    progressed = True
            if not progressed:
                remaining = sorted(set(by_id) - resolved)
                raise PlanValidationError(f"Plan has a dependency cycle among: {remaining}")
        return ordered

    # -- parsing ----------------------------------------------------------- #
    @staticmethod
    def _parse(raw: Any) -> Plan:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise PlanValidationError("Plan must be a JSON object.")
        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, list):
            raise PlanValidationError("Plan 'steps' must be a list.")
        steps: list[Step] = []
        for item in steps_raw:
            if not isinstance(item, dict):
                raise PlanValidationError("Each step must be an object.")
            sid = str(item.get("step_id", "")).strip()
            prim = str(item.get("primitive", "")).strip()
            if not sid or not prim:
                raise PlanValidationError("Each step needs 'step_id' and 'primitive'.")
            args = item.get("args") or {}
            depends_on = item.get("depends_on") or []
            if not isinstance(args, dict):
                raise PlanValidationError(f"Step {sid!r} 'args' must be an object.")
            if not isinstance(depends_on, list):
                raise PlanValidationError(f"Step {sid!r} 'depends_on' must be a list.")
            steps.append(
                Step(step_id=sid, primitive=prim, args=args, depends_on=[str(d) for d in depends_on])
            )
        return Plan(
            steps=steps,
            explanation=str(raw.get("explanation", "")),
            source="planner",
        )

    @staticmethod
    def _build_prompt(
        question: str, registry: Registry, context: Optional[dict[str, Any]]
    ) -> str:
        catalogue = json.dumps(registry.describe(), indent=2)
        ctx = json.dumps(context or {}, indent=2)
        return (
            f"Question:\n{question}\n\n"
            f"Available primitives (catalogue):\n{catalogue}\n\n"
            f"Context (known paths, terms, etc.):\n{ctx}\n\n"
            "Produce a JSON object with keys 'explanation' (string) and 'steps' "
            "(array). Each step has: 'step_id' (unique string), 'primitive' (a "
            "name from the catalogue), 'args' (object), and optional 'depends_on' "
            "(array of step_ids).\n\n"
            "ARGS CONTRACT -- follow exactly:\n"
            "- For each step, the 'args' object MUST use exactly the keys listed "
            "in that primitive's 'inputs' map. Do not invent, rename, omit "
            "(unless marked optional) or nest extra keys.\n"
            "- To feed an upstream step's output into an arg, use a reference "
            'object: {"$from": "<step_id>", "path": "<one of that step\'s '
            "'outputs' keys>\"}. The path MUST be one of the exact keys in the "
            "upstream primitive's 'outputs' map (e.g. \"payload.pages\"). Never "
            "guess a path that is not listed there.\n"
            "- For literal values (file paths, term lists, labels) copy directly "
            "from the Context above; do not wrap them in a reference object.\n"
            "- Add the producing step's id to 'depends_on' for every reference "
            "you use.\n\n"
            "Worked snippet (shapes only):\n"
            '{"step_id": "load_doc", "primitive": "connector.prospectus", '
            '"args": {"path": "<context path>"}}\n'
            '{"step_id": "extract", "primitive": "extractor.definitions", '
            '"depends_on": ["load_doc"], "args": {"pages": {"$from": "load_doc", '
            '"path": "payload.pages"}, "terms": ["arrears"], "document": '
            '{"$from": "load_doc", "path": "payload.document"}}}\n\n'
            "Only reference primitives that exist in the catalogue. Return JSON only."
        )


def _iter_refs(value: Any) -> set[str]:
    """Collect all ``$from`` step_ids referenced anywhere inside ``value``."""
    found: set[str] = set()
    if isinstance(value, dict):
        if "$from" in value and isinstance(value["$from"], str):
            found.add(value["$from"])
        for v in value.values():
            found |= _iter_refs(v)
    elif isinstance(value, list):
        for v in value:
            found |= _iter_refs(v)
    return found
