"""Append-only JSONL audit logger -- the governance evidence of every run.

Each primitive invocation produces an :class:`~sf_agents.primitives.base.AuditRecord`.
The :class:`AuditLogger` appends each record as one JSON line to a per-run file.
Append-only means: we only ever open files in append mode and never rewrite
earlier lines, so the log is tamper-evident by construction.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from ..primitives.base import AuditRecord


class AuditLogger:
    """Writes :class:`AuditRecord` entries to an append-only JSONL file.

    Args:
        audit_dir: Directory to hold audit files (created if absent).
        run_id: Identifier for this run; also the audit file stem.
    """

    def __init__(self, audit_dir: Path, run_id: str) -> None:
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._run_id = run_id
        self._path = self._dir / f"{run_id}.audit.jsonl"
        self._lock = threading.Lock()
        self._count = 0

    @property
    def path(self) -> Path:
        """Filesystem path of this run's audit log."""
        return self._path

    @property
    def count(self) -> int:
        """Number of records written so far."""
        return self._count

    def record(self, record: AuditRecord) -> None:
        """Append one audit record. Thread-safe and append-only."""
        line = json.dumps(record.as_dict(), sort_keys=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._count += 1

    def read_all(self) -> list[dict]:
        """Read back every record (for tests and post-run inspection)."""
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


def open_logger(audit_dir: Path, run_id: str) -> AuditLogger:
    """Convenience factory mirroring the constructor."""
    return AuditLogger(audit_dir, run_id)
