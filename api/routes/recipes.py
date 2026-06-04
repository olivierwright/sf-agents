"""GET /api/recipes — static catalogue of runnable recipes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

_CATALOGUE = [
    {
        "id": "definition_transparency",
        "label": "Definition Transparency",
        "description": (
            "How does the prospectus formally define key performance terms (arrears, "
            "default, cure), how does the ongoing investor report use those same terms, "
            "and where do the two diverge materially?"
        ),
        "terms": ["arrears", "default", "cure"],
        "needs_clarification": False,
        "clarification_options": None,
    },
    {
        "id": "impact_mapping",
        "label": "Impact Mapping",
        "description": (
            "Do the green/social claims made in the prospectus and the ISS second-party "
            "opinion actually hold up against the loan tape, and are the CFP impact "
            "report's figures consistent with what the tape shows?"
        ),
        "terms": ["EPC label", "primary energy demand", "construction deposit", "energy efficiency"],
        "needs_clarification": True,
        "clarification_options": [
            {"label": "Focus on EPC labels only", "value": "epc_only", "recommended": True},
            {"label": "Include energy demand metrics", "value": "energy_demand", "recommended": False},
            {"label": "Full green assessment", "value": "full", "recommended": False},
        ],
    },
]


@router.get("/recipes")
async def list_recipes() -> list[dict]:
    return _CATALOGUE
