"""Tests for connector.remittance_file."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from sf_agents.primitives.base import PrimitiveInput
from sf_agents.primitives.connectors.remittance_file import RemittanceFileConnector


def _write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "remittance.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_loads_csv(tmp_path):
    rows = [
        {"period": "2026-01", "period_collections": 50000.0, "scheduled_interest": 10000.0},
        {"period": "2026-02", "period_collections": 52000.0, "scheduled_interest": 10100.0},
        {"period": "2026-03", "period_collections": 48000.0, "scheduled_interest": 9900.0},
    ]
    path = _write_csv(tmp_path, rows)
    conn = RemittanceFileConnector()
    out = conn(PrimitiveInput(args={"path": str(path)}))

    assert out.payload["row_count"] == 3
    assert "period_collections" in out.payload["columns"]
    assert len(out.payload["rows"]) == 3
    assert out.confidence == 1.0


def test_citations_anchor_time_range(tmp_path):
    rows = [
        {"period": "2026-01", "period_collections": 50000.0},
        {"period": "2026-02", "period_collections": 52000.0},
    ]
    path = _write_csv(tmp_path, rows)
    conn = RemittanceFileConnector()
    out = conn(PrimitiveInput(args={"path": str(path)}))

    locations = [c.location for c in out.citations]
    assert "row=0" in locations
    assert "row=1" in locations


def test_max_rows_cap(tmp_path):
    rows = [{"period": f"2026-{i:02d}", "collections": float(i * 1000)} for i in range(1, 13)]
    path = _write_csv(tmp_path, rows)
    conn = RemittanceFileConnector()
    out = conn(PrimitiveInput(args={"path": str(path), "max_rows": 3}))

    assert out.payload["row_count"] == 3


def test_missing_file_raises():
    conn = RemittanceFileConnector()
    with pytest.raises(FileNotFoundError):
        conn(PrimitiveInput(args={"path": "/nonexistent/remittance.csv"}))
