"""Validator tests against the REAL Green Lion loan tape columns."""

from __future__ import annotations

from sf_agents.config import get_config
from sf_agents.primitives.base import PrimitiveInput
from sf_agents.primitives.connectors.loan_tape import LoanTapeConnector
from sf_agents.primitives.validators.esma_schema import (
    REQUIRED_FIELDS,
    EsmaSchemaValidator,
)

TAPE = "green_lion_2026_1_synthetic_loan_tape.csv"


def _load_tape(max_rows: int | None = None):
    cfg = get_config()
    conn = LoanTapeConnector()
    args = {"path": str(cfg.deal_file(TAPE))}
    if max_rows is not None:
        args["max_rows"] = max_rows
    return conn(PrimitiveInput(args=args))


def test_real_tape_passes_schema_validation():
    tape = _load_tape(max_rows=50)
    validator = EsmaSchemaValidator()
    out = validator(
        PrimitiveInput(
            args={
                "columns": tape.payload["columns"],
                "rows": tape.payload["rows"],
                "document": tape.payload["document"],
            }
        )
    )
    assert out.payload["ok"] is True, out.payload
    assert out.payload["missing_fields"] == []
    assert out.confidence == 1.0


def test_missing_field_is_reported():
    validator = EsmaSchemaValidator()
    cols = [c for c in REQUIRED_FIELDS if c != "default_crr_flag"]
    out = validator(PrimitiveInput(args={"columns": cols, "rows": [], "document": "t"}))
    assert out.payload["ok"] is False
    assert "default_crr_flag" in out.payload["missing_fields"]
    assert out.confidence < 1.0


def test_bad_flag_value_is_a_violation():
    validator = EsmaSchemaValidator()
    rows = [{"default_crr_flag": "MAYBE"}]
    out = validator(
        PrimitiveInput(
            args={"columns": list(REQUIRED_FIELDS), "rows": rows, "document": "t"}
        )
    )
    assert any("not a Y/N" in v for v in out.payload["violations"])
