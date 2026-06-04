# sf-agents

**An open, structured-finance agent framework.** Clean contracts, a dynamic
planner that composes audited primitives into an inspectable JSON DAG, and a
verifier that refuses to ship an answer whose citations don't resolve to a real
source page or row.

Hypoport's entry for the **Structured Finance Hackathon 2026** (FINOS,
Barcelona). Apache-2.0, neutral governance — built so another team can extend it
the same day.

> The bundled Green Lion 2026-1 data is **synthetic**. See `NOTICE`.

---

## Quick Start — Clone to Running App

### Prerequisites

| Tool       | Version     | Check             |
|------------|-------------|-------------------|
| Python     | 3.10+       | `python --version` |
| Node.js    | 20+         | `node --version`  |
| npm        | 10+         | `npm --version`   |
| Git        | any         | `git --version`   |

### 1. Clone the repo

```powershell
git clone https://github.com/hypoport/sf-agents.git
cd sf-agents
```

### 2. Create a Python virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Python dependencies

```powershell
pip install -e ".[dev]"
```

This installs the `sf-agents` package in editable mode plus dev tools (pytest).

### 4. Install the UI (Angular)

```powershell
cd ui
npm install
cd ..
```

### 5. Configure environment variables

Create a `.env` file in the project root (or edit the existing one):

```env
AWS_REGION=eu-north-1
AWS_ACCESS_KEY_ID=<your-key>
AWS_SECRET_ACCESS_KEY=<your-secret>
BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-6
```

The API server loads `.env` automatically via `python-dotenv` on startup — no
need to export variables manually.

> **Important:** You must set either `BEDROCK_INFERENCE_PROFILE_ARN` (preferred)
> or `BEDROCK_MODEL_ID`. There is no default model. Use a model your AWS account
> can actually invoke in the configured region.

### 6. Start the full stack

```powershell
.\start.ps1
```

This launches:
- **Backend** — FastAPI on `http://localhost:8000`
- **Frontend** — Angular dev server on `http://localhost:4200` (proxies `/api` → `:8000`)

Open **http://localhost:4200** in your browser.

### Alternative: Start services manually

```powershell
# Terminal 1 — Backend
.\.venv\Scripts\Activate.ps1
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Frontend
cd ui
npx ng serve --proxy-config proxy.conf.json
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No Bedrock model configured` | `.env` missing or `BEDROCK_MODEL_ID` not set | Ensure `.env` exists in project root with the variable set |
| `ModuleNotFoundError: dotenv` | `python-dotenv` not installed | Run `pip install -e ".[dev]"` again |
| Angular build errors | Node modules missing | `cd ui && npm install` |
| Port 8000 in use | Stale process | `start.ps1` auto-kills it; or manually `Stop-Process` |

---

## Why it's different

Most "agent" demos return prose you have to trust. `sf-agents` is built around
three guarantees:

1. **Every primitive returns evidence, not prose.** A `PrimitiveOutput` carries a
   structured `payload`, `citations`, a `confidence` score and `issues` — never a
   bare string.
2. **Every call is audited.** `BasePrimitive.__call__` times the call and appends
   an `AuditRecord` to an append-only JSONL log. The audit trail is a byproduct,
   not an afterthought.
3. **Every citation is verified.** The `Verifier` checks each citation against the
   real source index (which pages/rows actually exist). A hallucinated `page=999`
   fails the run.

## Architecture

```
            ┌─────────────────────────────────────────────────────────┐
            │                       RECIPE                             │
            │   (a question + the real Green Lion sample data)         │
            └─────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────┬───────────┼───────────────┬──────────────────┐
        ▼              ▼           ▼                ▼                  ▼
    REGISTRY  ───►  PLANNER  ───►  EXECUTOR  ───►  VERIFIER  ───►  cited answer
  (catalogue of   (LLM builds   (runs the DAG,   (every citation   + audit log
   primitives)    a JSON DAG;   resolves deps,   must resolve to
                  deterministic retries once,    a real page/row)
                  fallback)     routes low-conf
                                to human review)

  PRIMITIVES (fixed, tested building blocks the planner may compose):
    connector.prospectus · connector.pdf_document · connector.investor_report
    connector.loan_tape · validator.esma_schema · extractor.definitions
    analyzer.definition_comparator · analyzer.claim_vs_collateral
```

The design is **hybrid**: fixed, individually tested primitives + dynamic LLM
orchestration. The provider boundary is thin — **only** `primitives/_llm.py`
imports `boto3`, and every LLM-backed primitive accepts an injected `llm=` so the
whole stack runs offline in tests.

## Run the CLI demos

**Offline** (deterministic mock LLM, no AWS needed):

```powershell
python examples/01_definition_transparency.py --offline
python examples/02_impact_mapping.py --offline
```

**Live** (requires configured `.env` with AWS credentials):

```powershell
python examples/01_definition_transparency.py
python examples/02_impact_mapping.py
```

## Recipe 1: `definition_transparency`

Answers: *how does the prospectus define **arrears**, **default** and **cure**,
how does the monthly investor report use those same terms, and where do they
diverge materially?*

## Recipe 2: `impact_mapping`

Answers: *do the green/social claims made in the prospectus and the ISS
second-party opinion actually hold up against the loan tape and the CFP impact
report?*

Each verdict — *supported · partially supported · not supported · not verifiable
from data* — is **dual-grounded**: the verifier resolves the document page **and**
the tape row/column behind it, or the run fails.

## Run the tests

```powershell
pytest -q
```

The suite is fully offline: real PDFs/CSV, mocked LLM, no Bedrock or network.

## Add a primitive

1. Subclass `BasePrimitive`, set `name` / `version` / `capability`, implement
   `run(self, inp) -> PrimitiveOutput`. Populate `citations` for any claim.
2. For LLM-backed primitives, accept `llm=` in `__init__` and default it to
   `sf_agents.primitives._llm.complete_json` via a lazy import.
3. Register it in `build_default_registry` so the planner can compose it.
4. Add a unit test (offline). See `tests/` for patterns.

To add a whole recipe, see [`src/sf_agents/recipes/README.md`](src/sf_agents/recipes/README.md).

## Governance & licence

Apache-2.0 (`LICENSE`). Neutral, vendor-agnostic governance (`NOTICE`): the
framework takes no dependency on any single LLM provider beyond the thin
`_llm.py` boundary, and contributions are welcome from any party.
