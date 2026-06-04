# Recipes

A **recipe** is an end-to-end, runnable analysis. It wires the orchestrator
(`registry → planner → executor → verifier`) around one concrete question and the
real sample data, and returns a structured, cited, verified result.

Recipes are the unit a demo (or another team) actually runs.

## Shipped recipes

| Recipe | Question | Entry point |
| --- | --- | --- |
| `definition_transparency` | How do the prospectus and the monthly investor report define/use *arrears*, *default* and *cure*, and where do they diverge materially? | [`run_definition_transparency`](definition_transparency.py) |

## How to add a recipe

1. **Create a module** under `src/sf_agents/recipes/your_recipe.py`.
2. **Build a registry** with `build_default_registry(llm=...)`. Add new
   primitives there if your recipe needs capabilities that don't exist yet.
3. **Write a deterministic fallback `Plan`** (`build_fallback_plan(...)`) — the
   proven DAG that runs when the LLM planner is unavailable. Wire upstream
   outputs into downstream args with reference objects:
   `{"$from": "<step_id>", "path": "payload.<field>"}`.
4. **Call the planner** with your question, the registry and the fallback. The
   planner tries the LLM first and logs which path it took.
5. **Execute** with `Executor(registry, audit_logger=...)` and **verify** with
   `Verifier().verify(outputs, sources)`. Never return an answer whose citations
   did not verify.
6. **Return a structured dict** (plan, answer, comparisons, verification,
   review_queue, audit_path) so it is testable offline with a mock LLM.
7. **Add an example** under `examples/` and an offline e2e test under `tests/`.

Keep the provider boundary thin: only `primitives/_llm.py` imports `boto3`.
Inject `llm=` everywhere so the whole recipe runs offline in tests.
