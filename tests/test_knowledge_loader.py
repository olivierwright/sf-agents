"""Offline tests for the structured finance knowledge base loader."""
from __future__ import annotations

from sf_agents.knowledge.loader import (
    domain_preamble,
    green_section,
    load_full,
    load_section,
)


def test_load_full_returns_nonempty():
    text = load_full()
    assert isinstance(text, str)
    assert len(text) > 1000


def test_load_section_part4_contains_epc():
    section = load_section("PART 4")
    assert section, "PART 4 should not be empty"
    assert "EPC" in section


def test_load_section_missing_returns_empty():
    assert load_section("PART 99") == ""


def test_domain_preamble_under_60_lines():
    preamble = domain_preamble()
    lines = preamble.splitlines()
    assert len(lines) <= 60, f"domain_preamble() has {len(lines)} lines, must be ≤ 60"


def test_domain_preamble_nonempty():
    preamble = domain_preamble()
    assert preamble.strip()


def test_green_section_contains_ped():
    section = green_section()
    assert "PED" in section or "Primary Energy Demand" in section


def test_load_section_part6_contains_loan_fields():
    section = load_section("PART 6")
    assert "epc_label" in section or "loan_id" in section


def test_load_section_part8_contains_forbearance():
    section = load_section("PART 8")
    assert "forbearance" in section.lower()
