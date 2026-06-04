"""Compare how two sources define/operationalise the same terms.

Given two sets of per-term entries (each with a definition or usage, a page and
a verbatim excerpt), this LLM-backed analyzer pairs them by term and scores the
divergence as ``material`` | ``moderate`` | ``none`` with a short rationale.

Citations are built from the *input* entries that were actually compared (their
real page numbers and excerpts), not from anything the model invents -- so every
citation resolves against a real source chunk in the verifier.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

JsonLLM = Callable[..., Any]

_VALID_MATERIALITY = {"material", "moderate", "none"}

_SYSTEM = (
    "You are a structured-finance documentation analyst. You compare how two "
    "sources define or operationalise the same term and judge whether the "
    "difference is material to an investor. Be precise and conservative."
)


class DefinitionComparator(BasePrimitive):
    """Pair term definitions from two sources and score their differences.

    Input args:
        source_a (str): Name/label of the first source (e.g. the prospectus).
        source_b (str): Name/label of the second source (e.g. investor report).
        definitions_a (list[dict]): ``[{term, definition, page, excerpt}, ...]``.
        definitions_b (list[dict]): same shape from the second source.

    Payload:
        ``{"source_a", "source_b", "comparisons": [{term, materiality,
           rationale, a_excerpt, b_excerpt, a_page, b_page}...]}``
    """

    name = "analyzer.definition_comparator"
    version = "0.1.0"
    capability = (
        "Compare per-term definitions/usage from two sources, pair them by term, "
        "and score each difference as material / moderate / none with a rationale. "
        "Use after extracting definitions from each source."
    )
    inputs = {
        "source_a": "str: a label for the first source (literal, e.g. the prospectus name).",
        "source_b": "str: a label for the second source (literal, e.g. the investor report name).",
        "definitions_a": "list[{term, definition, page, excerpt}]: reference the first extractor's payload.definitions.",
        "definitions_b": "list[{term, definition, page, excerpt}]: reference the second extractor's payload.definitions.",
    }
    outputs = {
        "payload.source_a": "str: echoed label.",
        "payload.source_b": "str: echoed label.",
        "payload.comparisons": "list[{term, materiality, rationale, a_excerpt, b_excerpt, a_page, b_page}]: the scored comparison (final answer).",
    }

    def __init__(self, llm: Optional[JsonLLM] = None, audit_hook=None) -> None:
        super().__init__(audit_hook=audit_hook)
        if llm is None:
            from .._llm import complete_json as llm
        self._llm = llm

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        source_a = inp.get("source_a", "source_a")
        source_b = inp.get("source_b", "source_b")
        defs_a = {self._key(d): d for d in (inp.get("definitions_a", []) or [])}
        defs_b = {self._key(d): d for d in (inp.get("definitions_b", []) or [])}

        shared = [t for t in defs_a if t in defs_b]
        only_a = sorted(set(defs_a) - set(defs_b))
        only_b = sorted(set(defs_b) - set(defs_a))

        issues: list[str] = []
        if not shared:
            issues.append("No terms are defined in both sources; nothing to compare.")
            return PrimitiveOutput(
                payload={"source_a": source_a, "source_b": source_b, "comparisons": []},
                confidence=0.0 if (defs_a or defs_b) else 1.0,
                issues=issues,
                metadata={"only_a": only_a, "only_b": only_b},
            )

        prompt = self._build_prompt(source_a, source_b, shared, defs_a, defs_b)
        raw = self._llm(prompt, system=_SYSTEM, max_tokens=2048)
        scored = self._index_scores(raw)

        comparisons: list[dict[str, Any]] = []
        citations: list[Citation] = []
        for term in shared:
            a = defs_a[term]
            b = defs_b[term]
            verdict = scored.get(term, {})
            materiality = str(verdict.get("materiality", "")).strip().lower()
            if materiality not in _VALID_MATERIALITY:
                materiality = "moderate"
                issues.append(f"Model gave no valid materiality for '{term}'; defaulted to moderate.")
            rationale = str(verdict.get("rationale", "")).strip()
            comparisons.append(
                {
                    "term": a.get("term", term),
                    "materiality": materiality,
                    "rationale": rationale,
                    "a_excerpt": a.get("excerpt", ""),
                    "a_page": a.get("page"),
                    "b_excerpt": b.get("excerpt", ""),
                    "b_page": b.get("page"),
                }
            )
            # Citations come from the real input entries on both sides.
            citations.extend(self._entry_citations(source_a, a))
            citations.extend(self._entry_citations(source_b, b))

        # Confidence: fraction of shared terms the model actually scored validly.
        scored_ok = sum(
            1 for c in comparisons if c["materiality"] in _VALID_MATERIALITY
        )
        confidence = round(scored_ok / len(shared), 4) if shared else 1.0
        if only_a:
            issues.append(f"Only in {source_a}: {', '.join(only_a)}.")
        if only_b:
            issues.append(f"Only in {source_b}: {', '.join(only_b)}.")

        return PrimitiveOutput(
            payload={
                "source_a": source_a,
                "source_b": source_b,
                "comparisons": comparisons,
            },
            citations=citations,
            confidence=confidence,
            issues=issues,
            metadata={"shared_terms": shared, "only_a": only_a, "only_b": only_b},
        )

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _key(entry: dict[str, Any]) -> str:
        return str(entry.get("term", "")).strip().lower()

    @staticmethod
    def _entry_citations(source: str, entry: dict[str, Any]) -> list[Citation]:
        page = entry.get("page")
        excerpt = str(entry.get("excerpt", "")).strip()
        if isinstance(page, int) and excerpt:
            return [Citation(source=source, location=f"page={page}", excerpt=excerpt[:240])]
        return []

    @staticmethod
    def _build_prompt(
        source_a: str,
        source_b: str,
        shared: list[str],
        defs_a: dict[str, dict[str, Any]],
        defs_b: dict[str, dict[str, Any]],
    ) -> str:
        lines = []
        for term in shared:
            a = defs_a[term]
            b = defs_b[term]
            lines.append(
                f"TERM: {a.get('term', term)}\n"
                f"  [{source_a}] {a.get('definition', '')}\n"
                f"  [{source_b}] {b.get('definition', '')}"
            )
        body = "\n\n".join(lines)
        return (
            f"Compare how '{source_a}' and '{source_b}' define or operationalise "
            "each term below. For each term, judge whether the difference is "
            "'material', 'moderate' or 'none' from an investor's perspective and "
            "give a one-sentence rationale.\n\n"
            "Return a JSON array of objects with keys: 'term', 'materiality' "
            "(one of material/moderate/none) and 'rationale'.\n\n"
            f"{body}"
        )

    @staticmethod
    def _index_scores(raw: Any) -> dict[str, dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if isinstance(raw, list):
            records = [r for r in raw if isinstance(r, dict)]
        elif isinstance(raw, dict):
            for key in ("comparisons", "results", "items"):
                if isinstance(raw.get(key), list):
                    records = [r for r in raw[key] if isinstance(r, dict)]
                    break
            else:
                records = [raw]
        return {str(r.get("term", "")).strip().lower(): r for r in records}
