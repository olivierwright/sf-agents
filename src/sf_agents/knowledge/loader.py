"""Knowledge base loader for the sf-agents domain reference document.

Reads structured_finance.md once per process (lru_cache). All public
functions are pure Python — no LLM calls, no side effects.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

KNOWLEDGE_PATH = Path(__file__).parent / "structured_finance.md"

_PART_HEADER = "## PART"


@lru_cache(maxsize=1)
def load_full() -> str:
    """Load the complete knowledge base. Cached — read once per process."""
    if not KNOWLEDGE_PATH.exists():
        raise FileNotFoundError(
            f"Structured finance knowledge base not found at: {KNOWLEDGE_PATH}. "
            "Ensure src/sf_agents/knowledge/structured_finance.md is present."
        )
    return KNOWLEDGE_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def load_section(section_title: str) -> str:
    """Extract a specific ## PART section by its title prefix.

    Splits on '## PART' headers. Returns the full section text (including all
    subsections) for the first section whose header starts with the given title.
    Returns empty string if not found.

    Example:
        load_section("PART 4")  →  full text of PART 4 including 4.1, 4.2, 4.3
    """
    full = load_full()
    lines = full.splitlines(keepends=True)

    start: int | None = None
    end: int | None = None

    # Normalise: accept either "PART 4" or "4" as section_title
    normalised = section_title.strip()
    if normalised.upper().startswith("PART "):
        normalised = normalised[5:].strip()  # strip leading "PART " → "4"

    for i, line in enumerate(lines):
        if line.startswith(_PART_HEADER):
            header_text = line.strip()
            # Header format: "## PART 4 — ..."  match by number after "## PART "
            after_prefix = header_text[len(_PART_HEADER):].strip()  # "4 — ..."
            if after_prefix == normalised or after_prefix.startswith(normalised + " "):
                start = i
            elif start is not None:
                end = i
                break

    if start is None:
        return ""
    section_lines = lines[start:end] if end is not None else lines[start:]
    return "".join(section_lines).strip()


def domain_preamble() -> str:
    """Return a compact preamble (≤ 60 lines) for injection into agent system prompts.

    Covers: key terminology, critical gotchas, and pointers to the full document.
    Cached via load_full().
    """
    return """\
STRUCTURED FINANCE DOMAIN CONTEXT (European RMBS focus, Dutch market):

KEY ROLES: Originator sells loans to a bankruptcy-remote SPV. Servicer collects
payments. Trustee enforces for noteholders. Calculation agent computes waterfall.

TRANCHING: Senior (AAA) paid first; mezzanine absorbs next losses; equity/Z tranche
absorbs first losses. Credit enhancement = subordination + reserve fund + excess spread
+ overcollateralisation + NHG guarantee (Netherlands, covers loans ≤ €435k as of 2025).

WATERFALL: Interest waterfall pays senior fees → Class A interest → PDL replenishment
→ reserve fund → junior tranches → residual. PDL (Principal Deficiency Ledger) debits
signal realised losses. ADA = Available Distribution Amount = collections + recoveries
− defaults.

KEY METRICS:
- CPR (Constant Prepayment Rate): annualised voluntary prepayment. CPR = 1−(1−SMM)^12.
  Do NOT confuse with CDR (Constant Default Rate) — they measure opposite behaviours.
- CDR: annualised default rate. Defaults = servicer-determined loss events.
- WA LTV: weighted by balance, use current (CLTOMV) not origination (OLTOMV) for loss severity.
- Arrears thresholds vary by deal — ALWAYS check the prospectus definition.
  Common: 30+/60+/90+ days past due; Dutch deals often use 180+ for formal default.
- Cure: return to performing after consecutive on-time payments. Number of payments
  required is DEAL-SPECIFIC — never assume 3 payments.

GREEN / ESG:
- EPC labels (Netherlands): post-2021 NTA 8800 scale (A++++ to G) ≠ pre-2021 scale.
  An A label pre-2021 is NOT equivalent to an A label post-2021.
- PED (Primary Energy Demand, kWh/m²/year): typical SPO thresholds — 27 kWh/m² for
  houses, 45 for apartments (ISS SPO frameworks). Prospectus and SPO thresholds may differ.
- EPC certificates expire after 10 years (check epc_issue_year vs reporting_date).
- SPO verifies framework design only — it does NOT verify individual loan compliance.
  Actual green share must be verified from the loan tape.
- "Green share" depends on which criterion you apply — EPC label vs PED threshold
  can give very different results. Always state which criterion you measured.

CRITICAL GOTCHAS:
- Forbearance masks arrears: a forborne loan may show 0 days past due but is under stress.
  Always check forbearance_flag alongside arrears_bucket.
- ESMA ND codes (ND1–ND5) are not zeros — high ND rates on critical fields limit analysis.
- Origination LTV ≠ current LTV. Dutch house prices rose 2020-2022; seasoned pools
  have meaningfully lower loss severity than origination LTV implies.
- CPR in investor reports is often 1-month annualised — confirm basis before benchmarking.
- ESMA CRR Article 178 default definition may differ from deal-level waterfall default trigger.

REGULATION: EU Securitisation Regulation 2017/2402 governs. STS = Simple, Transparent,
Standardised — preferential capital treatment. Risk retention ≥5% mandatory (Article 6).
ESMA Annex 2 loan-level template mandatory since 1 Oct 2024 for Eurosystem eligibility.
"""


def green_section() -> str:
    """Return PART 4 (Green / Sustainable RMBS) only."""
    return load_section("PART 4")


def definitions_section() -> str:
    """Return PART 6 (Loan Tape Fields) and PART 8 (Gotchas) combined."""
    part6 = load_section("PART 6")
    part8 = load_section("PART 8")
    parts = [p for p in (part6, part8) if p]
    return "\n\n".join(parts)


def waterfall_section() -> str:
    """Return the waterfall content from PART 2."""
    return load_section("PART 2")


def regulatory_section() -> str:
    """Return PART 3 (Regulatory Framework)."""
    return load_section("PART 3")


def deal_documents_section() -> str:
    """Return PART 5 (Deal Documents)."""
    return load_section("PART 5")


def questions_section() -> str:
    """Return PART 7 (Questions an Agent Should Answer)."""
    return load_section("PART 7")


def gotchas_section() -> str:
    """Return PART 8 (Common Misconceptions and Gotchas)."""
    return load_section("PART 8")


def rmbs_section() -> str:
    """Return PART 2 (RMBS Specifics)."""
    return load_section("PART 2")
