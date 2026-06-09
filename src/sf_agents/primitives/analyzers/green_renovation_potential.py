"""Deterministic renovation-potential segmentation for mortgage portfolios.

Applies a three-way commercial filter to identify loans where the bank could
realistically run a green renovation campaign:
  1. EPC label below A  (genuine energy improvement potential)
  2. Remaining term > 48 months  (enough time to justify a renovation product)
  3. Current LTV < 80%  (borrower has ~20%+ equity headroom for an extra energy loan)

Returns exact counts, balances, EPC/province/PED breakdowns, a criteria funnel,
and a 30%-renovate-to-A scenario. All arithmetic is deterministic — no LLM.

Typical plan:
  connector.loan_tape → analyzer.green_renovation_potential
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Optional

from ..base import BasePrimitive, Citation, PrimitiveInput, PrimitiveOutput

# NL EPC label hierarchy (highest to lowest energy performance, post-2021 NTA 8800)
_EPC_ORDER = ["A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]
_EPC_RANK: dict[str, int] = {label: i for i, label in enumerate(_EPC_ORDER)}

# Rank threshold: loans with rank > _A_RANK are sub-A (renovation candidates)
_A_RANK = _EPC_RANK["A"]

# PED green thresholds (kWh/m²/year) by property type
# Houses: EU Taxonomy / typical DSA framework ceiling
# Apartments: same framework, higher allowance
_PED_THRESHOLD = {"House": 50.0, "Apartment": 70.0}
_PED_DEFAULT_THRESHOLD = 50.0


class GreenRenovationPotentialAnalyzer(BasePrimitive):
    """Deterministic renovation-potential segmentation over a loan tape.

    Identifies the sub-A, long-term, low-LTV segment that represents actionable
    green renovation opportunities for the bank's mortgage origination team.
    No LLM required.
    """

    name = "analyzer.green_renovation_potential"
    version = "0.1.0"
    capability = (
        "Identify mortgage loans with green renovation potential: EPC label below A, "
        "remaining term above 48 months, and current LTV below 80%. "
        "Returns exact loan counts, total balance, pool share, EPC label breakdown within "
        "the segment, average primary energy demand (kWh/m²) and gap to the green threshold, "
        "province concentration, and a '30% renovate to EPC A' scenario showing the green "
        "share uplift. All calculations are deterministic arithmetic — no LLM. "
        "Use after connector.loan_tape to answer commercial origination questions about "
        "where to focus a green renovation campaign."
    )
    inputs = {
        "columns": "list[str]: loan tape column names from connector.loan_tape payload.columns.",
        "rows": "list[dict]: loan tape rows from connector.loan_tape payload.rows.",
        "tape_document": "str: loan tape file name from connector.loan_tape payload.document.",
    }
    outputs = {
        "payload.segment": "Loan count, total balance, and pool share for the renovation segment.",
        "payload.epc_breakdown": "Per-label loan count, balance, and segment share within the segment.",
        "payload.ped_stats": "Mean/median PED and gap to green threshold for segment loans.",
        "payload.province_breakdown": "Per-province counts and balances within the segment.",
        "payload.criteria_funnel": "Step-by-step filter counts and the binding constraint.",
        "payload.scenario_30pct_renovate": "Green share before and after 30% of segment renovates to A.",
        "payload.data_quality_flags": "Data quality issues found during analysis.",
        "payload.summary": "4–6 sentence commercial narrative for the mortgage team.",
    }

    def run(self, inp: PrimitiveInput) -> PrimitiveOutput:
        rows: list[dict] = inp.get("rows") or []
        tape_doc: str = inp.get("tape_document") or "loan_tape"

        if not rows:
            return PrimitiveOutput(
                payload={"error": "No rows provided"},
                confidence=0.0,
                issues=["No loan tape rows received."],
            )

        issues: list[str] = []
        data_quality_flags: list[str] = []

        # ------------------------------------------------------------------
        # Step 1 — Parse each row into typed fields
        # ------------------------------------------------------------------
        parsed: list[dict[str, Any]] = []
        for row in rows:
            balance = _safe_float(row.get("current_balance"))
            ltv = _safe_float(row.get("cltomv_current"))
            term = _safe_float(row.get("remaining_term_months"))
            ped = _safe_float(row.get("primary_energy_demand_kwh_m2"))
            epc = (row.get("epc_label") or "").strip()
            province = (row.get("province") or "Unknown").strip()
            prop_type = (row.get("property_type") or "").strip()
            loan_id = row.get("loan_id") or ""
            parsed.append({
                "loan_id": loan_id,
                "balance": balance,
                "ltv": ltv,
                "term": term,
                "ped": ped,
                "epc": epc,
                "province": province,
                "prop_type": prop_type,
            })

        total_loans = len(parsed)
        total_balance = sum(p["balance"] or 0.0 for p in parsed)

        # ------------------------------------------------------------------
        # Step 2 — Criteria funnel
        # ------------------------------------------------------------------
        # Filter 1: EPC below A
        after_epc = [
            p for p in parsed
            if _epc_rank(p["epc"]) > _A_RANK
        ]
        # Filter 2: Remaining term > 48 months (4 years)
        after_term = [
            p for p in after_epc
            if p["term"] is not None and p["term"] > 48
        ]
        # Filter 3: Current LTV < 80%
        segment = [
            p for p in after_term
            if p["ltv"] is not None and p["ltv"] < 80.0
        ]

        # Binding constraint: whichever filter removed the most loans
        removed_by_epc = total_loans - len(after_epc)
        removed_by_term = len(after_epc) - len(after_term)
        removed_by_ltv = len(after_term) - len(segment)
        binding = max(
            ("epc_below_a", removed_by_epc),
            ("remaining_term_gt_48m", removed_by_term),
            ("ltv_below_80pct", removed_by_ltv),
            key=lambda x: x[1],
        )[0]

        criteria_funnel = {
            "total_pool": total_loans,
            "after_epc_filter": len(after_epc),
            "after_term_filter": len(after_term),
            "after_ltv_filter": len(segment),
            "binding_constraint": binding,
        }

        # ------------------------------------------------------------------
        # Step 3 — Segment summary
        # ------------------------------------------------------------------
        seg_count = len(segment)
        seg_balance = sum(p["balance"] or 0.0 for p in segment)

        segment_summary = {
            "loan_count": seg_count,
            "total_balance": round(seg_balance, 2),
            "pool_share_count_pct": _pct(seg_count, total_loans),
            "pool_share_balance_pct": _pct(seg_balance, total_balance),
        }

        # ------------------------------------------------------------------
        # Step 4 — EPC breakdown within segment
        # ------------------------------------------------------------------
        epc_map: dict[str, dict[str, Any]] = {}
        for p in segment:
            lbl = p["epc"] or "Unknown"
            if lbl not in epc_map:
                epc_map[lbl] = {"count": 0, "balance": 0.0}
            epc_map[lbl]["count"] += 1
            epc_map[lbl]["balance"] += p["balance"] or 0.0

        epc_breakdown: dict[str, dict[str, Any]] = {}
        for lbl in _EPC_ORDER + ["Unknown"]:
            if lbl in epc_map:
                entry = epc_map[lbl]
                epc_breakdown[lbl] = {
                    "count": entry["count"],
                    "balance": round(entry["balance"], 2),
                    "pct_of_segment": _pct(entry["count"], seg_count),
                }

        # ------------------------------------------------------------------
        # Step 5 — PED statistics within segment
        # ------------------------------------------------------------------
        ped_values = [p["ped"] for p in segment if p["ped"] is not None]
        # Compute weighted PED threshold (by property type)
        threshold_sum = 0.0
        threshold_n = 0
        for p in segment:
            t = _PED_THRESHOLD.get(p["prop_type"], _PED_DEFAULT_THRESHOLD)
            threshold_sum += t
            threshold_n += 1
        avg_threshold = threshold_sum / threshold_n if threshold_n else _PED_DEFAULT_THRESHOLD

        if ped_values:
            mean_ped = statistics.mean(ped_values)
            median_ped = statistics.median(ped_values)
            gap = avg_threshold - mean_ped  # negative = segment already below threshold
        else:
            mean_ped = median_ped = gap = 0.0
            data_quality_flags.append("No PED data available for segment loans.")

        ped_stats = {
            "mean_kwh_m2": round(mean_ped, 1),
            "median_kwh_m2": round(median_ped, 1),
            "green_threshold_used_kwh_m2": round(avg_threshold, 1),
            "avg_gap_to_green_threshold": round(gap, 1),
            "n_with_ped_data": len(ped_values),
        }

        # ------------------------------------------------------------------
        # Step 6 — Province breakdown within segment
        # ------------------------------------------------------------------
        prov_map: dict[str, dict[str, Any]] = {}
        for p in segment:
            prov = p["province"]
            if prov not in prov_map:
                prov_map[prov] = {"count": 0, "balance": 0.0}
            prov_map[prov]["count"] += 1
            prov_map[prov]["balance"] += p["balance"] or 0.0

        province_breakdown: dict[str, dict[str, Any]] = {
            prov: {
                "count": v["count"],
                "balance": round(v["balance"], 2),
                "pct_of_segment": _pct(v["count"], seg_count),
            }
            for prov, v in sorted(prov_map.items(), key=lambda x: -x[1]["count"])
        }

        # ------------------------------------------------------------------
        # Step 7 — 30% renovation scenario
        # ------------------------------------------------------------------
        # Current green = EPC rank <= A_RANK across the whole pool
        current_green = sum(1 for p in parsed if _epc_rank(p["epc"]) <= _A_RANK)
        loans_renovated = math.floor(seg_count * 0.30)
        new_green = current_green + loans_renovated

        scenario = {
            "loans_renovated": loans_renovated,
            "current_green_count": current_green,
            "current_green_share_pct": _pct(current_green, total_loans),
            "post_scenario_green_count": new_green,
            "post_scenario_green_share_pct": _pct(new_green, total_loans),
            "green_share_uplift_pp": round(
                _pct(new_green, total_loans) - _pct(current_green, total_loans), 2
            ),
        }

        # ------------------------------------------------------------------
        # Step 8 — Data quality flags
        # ------------------------------------------------------------------
        unknown_epc = sum(1 for p in parsed if not p["epc"] or p["epc"] == "Unknown")
        if unknown_epc:
            data_quality_flags.append(
                f"{unknown_epc} loan(s) have unknown or missing EPC label and cannot be verified."
            )
        missing_ltv = sum(1 for p in parsed if p["ltv"] is None)
        if missing_ltv:
            data_quality_flags.append(f"{missing_ltv} loan(s) missing current LTV (excluded from LTV filter).")
        missing_term = sum(1 for p in parsed if p["term"] is None)
        if missing_term:
            data_quality_flags.append(f"{missing_term} loan(s) missing remaining term (excluded from term filter).")

        # ------------------------------------------------------------------
        # Step 9 — Deterministic narrative summary
        # ------------------------------------------------------------------
        top_provinces = list(province_breakdown.keys())[:3]
        top_epc = list(epc_breakdown.keys())[:2]
        prov_str = ", ".join(top_provinces) if top_provinces else "unknown"
        epc_str = " and ".join(top_epc) if top_epc else "sub-A"

        if seg_count == 0:
            summary = (
                "No loans meet all three criteria (EPC below A, remaining term above 48 months, "
                "current LTV below 80%). The portfolio may already be fully green or the LTV "
                "filter is removing all candidates. Review the criteria funnel for detail."
            )
        else:
            gap_dir = "above" if gap > 0 else "below"
            gap_abs = abs(round(gap, 0))
            summary = (
                f"The Green Lion portfolio contains {seg_count:,} loans ({segment_summary['pool_share_count_pct']:.1f}% of the pool, "
                f"€{seg_balance/1e6:.0f}M outstanding) that meet all three renovation-campaign criteria: "
                f"EPC below A, at least 4 years of remaining term, and current LTV below 80%. "
                f"The dominant EPC labels within this segment are {epc_str}, concentrated in {prov_str}. "
                f"Average primary energy demand for segment loans is {mean_ped:.0f} kWh/m², "
                f"{gap_abs:.0f} kWh/m² {gap_dir} the green threshold — confirming genuine energy improvement potential. "
                f"If 30% of these borrowers renovate to EPC label A ({loans_renovated:,} loans), "
                f"the pool's green share rises from {scenario['current_green_share_pct']:.1f}% to "
                f"{scenario['post_scenario_green_share_pct']:.1f}% (+{scenario['green_share_uplift_pp']:.1f} percentage points)."
            )

        # ------------------------------------------------------------------
        # Citations
        # ------------------------------------------------------------------
        citations = [
            Citation(
                source=tape_doc,
                location=f"rows=0-{total_loans - 1}",
                excerpt=(
                    f"{seg_count} of {total_loans} loans pass EPC<A + term>48m + LTV<80% filter; "
                    f"pool balance €{total_balance/1e6:.1f}M"
                ),
            )
        ]

        payload = {
            "segment": segment_summary,
            "epc_breakdown": epc_breakdown,
            "ped_stats": ped_stats,
            "province_breakdown": province_breakdown,
            "criteria_funnel": criteria_funnel,
            "scenario_30pct_renovate": scenario,
            "data_quality_flags": data_quality_flags,
            "summary": summary,
        }

        return PrimitiveOutput(
            payload=payload,
            citations=citations,
            confidence=1.0,
            issues=issues,
            metadata={"tape_document": tape_doc, "total_loans_analysed": total_loans},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _epc_rank(label: str) -> int:
    """Return EPC rank (lower = better). Unknown labels get rank 999."""
    return _EPC_RANK.get((label or "").strip(), 999)


def _safe_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _pct(part: float, total: float) -> float:
    if not total:
        return 0.0
    return round(100.0 * part / total, 2)
