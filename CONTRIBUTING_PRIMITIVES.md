# Contributing Primitives

This document explains how to add a new primitive to the sf-agents framework.
A primitive is a reusable, versioned building block that the orchestrator can
compose into dynamic analysis workflows.

---

## The 5-Step Process

### 1. Copy the template

```bash
cp src/sf_agents/primitives/_template.py \
   src/sf_agents/primitives/<category>/<your_name>.py
```

Choose the right category directory:

| Directory      | Use for                                      |
|----------------|----------------------------------------------|
| `connectors/`  | Loading data (PDF, CSV, API, tape files)      |
| `extractors/`  | LLM-backed information extraction from pages  |
| `analyzers/`   | Reasoning and comparison (may use LLM)        |
| `validators/`  | Deterministic schema/rule checking (no LLM)  |

### 2. Set class attributes

Every primitive must declare four class-level attributes:

```python
name = "category.snake_case_name"   # globally unique — planner uses this
version = "0.1.0"                   # semver; bump on breaking changes
capability = "..."                   # one sentence; planner reads this to decide
inputs = {"arg": "type: description"}
outputs = {"payload.key": "type: description"}
```

**Name convention:** `<category>.<snake_case>` — e.g. `connector.esma_tape`,
`extractor.waterfall`, `analyzer.covenant_compliance`.

**Capability** is the most important attribute. The LLM planner reads it to
decide whether to include your primitive in a plan. Make it specific and action-
oriented: say what the primitive does and when to use it.

**Inputs/outputs contracts** are the typed interface your primitive advertises.
Other primitives' steps reference these exact keys in `$from` references.

### 3. Implement `run(inp)`

```python
def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
    # Read inputs
    value = inp.get("arg", default)

    # Do work
    result = {"payload_key": computed_value}

    # Build citations — mandatory for any claim
    citations = [Citation(source="doc.pdf", location="page=42", excerpt="verbatim text")]

    return PrimitiveOutput(
        payload=result,
        citations=citations,
        confidence=0.95,    # honest: 0.0 = no output, 1.0 = fully verified
        issues=[],          # non-fatal warnings, not exceptions
        metadata={},        # diagnostic info (timing, counts, etc.)
    )
```

#### Citation grounding — mandatory

Every claim in your output must be backed by a citation:

- `source`: the document or file name exactly as it was loaded
- `location`: `"page=42"` for PDFs, `"row=17"` for tabular data
- `excerpt`: text copied **verbatim** from the source (never invented)

The verifier will reject any run where a citation does not resolve to a real
source page or row.

#### Confidence scoring

Confidence must reflect **real coverage**, not model confidence:

- Connectors: `1.0` if data loaded successfully, `0.2` if image-only PDF
- Extractors: `found / requested` (e.g. extracted 2 of 3 terms → `0.667`)
- Analyzers: fraction of comparisons or assessments with valid citations
- Validators: `1.0` if required fields present, lower if fields missing

Outputs below the `confidence_floor` (default `0.70`) are routed to the human
review queue. The run continues — low confidence is a warning, not a failure.

#### Error handling

- **Raise exceptions** only for unrecoverable errors (file not found, bad format).
- **Use `issues`** for non-fatal warnings (missing optional field, low coverage).
- Never silently swallow errors — the executor will surface them.

### 4. Register in the registry

Open `src/sf_agents/orchestrator/registry.py` and add to `build_default_registry()`:

```python
# Deterministic primitive (no LLM):
registry.register(lambda hook: MyNewPrimitive(audit_hook=hook))

# LLM-backed primitive:
registry.register(lambda hook: MyNewPrimitive(llm=llm, audit_hook=hook))
```

The `llm` parameter passed to `build_default_registry()` defaults to the real
Bedrock client and is replaced by a mock in offline tests.

### 5. Write a test

Create `tests/test_<your_name>.py`. Your test must work fully offline:

```python
def test_my_primitive_produces_citations(mock_llm):
    # mock_llm is the offline LLM from conftest.py
    prim = MyNewPrimitive(llm=mock_llm)
    out = prim(PrimitiveInput(args={"arg": "value"}))

    assert out.confidence > 0
    assert len(out.citations) > 0
    assert out.citations[0].location.startswith("page=")
```

If your primitive is deterministic (no LLM), omit `mock_llm`:

```python
def test_my_validator_passes_valid_input():
    prim = MyNewValidator()
    out = prim(PrimitiveInput(args={"columns": [...], "rows": [...]}))
    assert out.payload["ok"] is True
```

To support your new mock responses, add a case to `conftest.py`'s `mock_llm`
fixture, keyed on the system prompt string.

---

## Key Invariants

| Rule | Why |
|------|-----|
| Only `_llm.py` imports `boto3` | Provider boundary stays thin; offline testing works |
| All claims need citations | Verifier checks every citation against real sources |
| Confidence = real coverage | Low confidence → human review; not a model guess |
| No network in tests | Tests must run offline (CI, no AWS credentials) |
| `issues` not exceptions | Non-fatal warnings are returned, not raised |
| Unique `name` | Registry raises on duplicate; name is the planner's reference |

---

## Primitive lifecycle

```
Planner selects primitive by capability
  → Registry builds fresh instance with audit_hook wired
    → Executor calls primitive.__call__(inp) [times it, records audit entry]
      → primitive.run(inp) is your code
        → PrimitiveOutput returned
          → Verifier checks all citations resolve
            → Low confidence → human review queue
              → Output fed to downstream steps via $from references
```

---

## Example: adding `connector.esma_tape`

```python
# src/sf_agents/primitives/connectors/esma_tape.py

class EsmaTapeConnector(BasePrimitive):
    name = "connector.esma_tape"
    version = "0.1.0"
    capability = (
        "Load an ESMA Annex 2 loan tape in CSV format. Returns columns and "
        "rows for use with validator.esma_schema or analyzer.cashflow_anomaly."
    )
    inputs = {
        "path": "str: filesystem path to the ESMA tape CSV.",
        "max_rows": "int, optional: cap on rows returned.",
    }
    outputs = {
        "payload.document": "str: file name.",
        "payload.columns": "list[str]: column names.",
        "payload.rows": "list[dict]: row records.",
        "payload.row_count": "int: number of rows.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        # ... (see LoanTapeConnector for the pattern)
```

Then register it and add `tests/test_esma_tape.py`.

---

## Getting help

- Open an issue or PR in this repo.
- Reference primitives to follow: `LoanTapeConnector`, `DefinitionExtractor`,
  `CovenantComplianceAnalyzer` (deterministic), `WaterfallExtractor` (LLM-backed).
