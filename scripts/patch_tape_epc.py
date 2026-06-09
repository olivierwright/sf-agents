"""Patch synthetic loan tapes to produce a realistic Dutch RMBS EPC distribution.

The original tapes were generated as post-screened green bond pools (99.97% EPC A+
or better). This script reassigns a subset of currently-A loans to sub-A labels
and updates their primary_energy_demand_kwh_m2 to plausible values, producing an
origination-book distribution suitable for renovation campaign analysis.

Target distribution (mirrors a typical Dutch origination book):
  A++++ – A+  ~60%
  A            ~5%
  B           ~18%
  C           ~12%
  D            ~4%
  E             ~1%

The RNG is seeded per loan_id so the patch is fully deterministic and reproducible.
Only epc_label and primary_energy_demand_kwh_m2 are modified; no schema changes.

Usage:
    python scripts/patch_tape_epc.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import random

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "Sample Data")

TAPE_FILES = [
    "green_lion_2026_1_synthetic_loan_tape.csv",
    "green_lion_202602_1_synthetic_loan_tape.csv",
    "green_lion_202603_1_synthetic_loan_tape.csv",
]

# EPC hierarchy (highest performance first)
_EPC_ORDER = ["A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]

# Target distribution for the full pool after patching.
# Expressed as fractions that must sum to 1.0.
_TARGET_DISTRIBUTION = {
    "A++++": 0.08,
    "A+++":  0.18,
    "A++":   0.08,
    "A+":    0.16,
    "A":     0.05,
    "B":     0.18,
    "C":     0.12,
    "D":     0.09,
    "E":     0.04,
    "F":     0.01,
    "G":     0.01,
}

# Plausible PED ranges (kWh/m²/year) per label for reassigned loans.
# Existing A/A+/A++/A+++/A++++ values are left untouched.
_PED_RANGES = {
    "B": (75,  150),
    "C": (150, 250),
    "D": (250, 325),
    "E": (325, 400),
    "F": (400, 460),
    "G": (460, 500),
}

# Seed prefix so patches across files are independent but still deterministic.
_SEED_PREFIX = "green_lion_epc_patch_v1"


def _loan_rng(loan_id: str, file_tag: str) -> random.Random:
    """Return a seeded RNG unique to (loan_id, file_tag)."""
    seed_bytes = hashlib.sha256(f"{_SEED_PREFIX}:{file_tag}:{loan_id}".encode()).digest()
    seed_int = int.from_bytes(seed_bytes[:8], "big")
    return random.Random(seed_int)


def _target_counts(n_loans: int) -> dict[str, int]:
    """Compute integer target counts from fractional distribution."""
    counts = {label: int(round(frac * n_loans)) for label, frac in _TARGET_DISTRIBUTION.items()}
    # Fix rounding drift so totals sum exactly to n_loans.
    diff = n_loans - sum(counts.values())
    if diff != 0:
        counts["A"] += diff
    return counts


def patch_file(filename: str) -> None:
    path = os.path.join(DATA_DIR, filename)
    file_tag = filename.replace(".csv", "")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    n = len(rows)
    target = _target_counts(n)
    print(f"\n{filename} — {n} loans")
    print(f"  Target counts: { {k: v for k, v in target.items()} }")

    # Count current distribution.
    current: dict[str, list[int]] = {lbl: [] for lbl in _EPC_ORDER}
    current["Unknown"] = []
    current["other"] = []
    for i, row in enumerate(rows):
        lbl = row.get("epc_label", "Unknown") or "Unknown"
        if lbl in current:
            current[lbl].append(i)
        else:
            current["other"].append(i)

    # Build a pool of A-family rows that can be reassigned.
    # We never reassign non-green rows that are already sub-A (there are very few).
    reassignable = (
        current["A++++"]
        + current["A+++"]
        + current["A++"]
        + current["A+"]
        + current["A"]
    )
    # Shuffle deterministically using file-level seed.
    rng_global = random.Random(hashlib.sha256(f"{_SEED_PREFIX}:{file_tag}:global".encode()).digest()[:8])
    rng_global.shuffle(reassignable)

    # Determine how many rows of each label we still need to reach target.
    # Keep existing sub-A rows as-is; only fill shortfall by reassigning A-family.
    reassignments: list[tuple[int, str]] = []  # (row_index, new_label)

    cursor = 0
    for label in ["A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]:
        have = len(current.get(label, []))
        need = target[label] - have
        if need <= 0:
            continue
        if cursor + need > len(reassignable):
            need = len(reassignable) - cursor
        for idx in reassignable[cursor: cursor + need]:
            reassignments.append((idx, label))
        cursor += need
        if cursor >= len(reassignable):
            break

    # Apply reassignments.
    for row_idx, new_label in reassignments:
        row = rows[row_idx]
        loan_id = row.get("loan_id", str(row_idx))
        rng = _loan_rng(loan_id, file_tag)
        row["epc_label"] = new_label
        if new_label in _PED_RANGES:
            lo, hi = _PED_RANGES[new_label]
            row["primary_energy_demand_kwh_m2"] = str(round(rng.uniform(lo, hi), 1))

    # Write back.
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Report final distribution.
    final: dict[str, int] = {}
    for row in rows:
        lbl = row.get("epc_label", "Unknown") or "Unknown"
        final[lbl] = final.get(lbl, 0) + 1
    sub_a = sum(v for k, v in final.items() if k not in ("A++++", "A+++", "A++", "A+", "A"))
    print(f"  Final distribution: { {k: v for k, v in sorted(final.items())} }")
    print(f"  Sub-A total: {sub_a} ({100*sub_a/n:.1f}%)")


if __name__ == "__main__":
    for tape in TAPE_FILES:
        patch_file(tape)
    print("\nDone. All three tapes patched.")
