"""Central, environment-driven configuration for sf-agents.

All tunables live here and are read from environment variables so that nothing
needs to be hard-coded. Bedrock model/credential settings are intentionally NOT
in this module -- they are read inside ``primitives/_llm.py`` only, to keep the
provider boundary thin.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _repo_root() -> Path:
    """Best-effort repository root (two levels up from ``src/sf_agents``)."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    """Runtime configuration resolved from the environment.

    Attributes:
        data_dir: Directory holding the sample deal documents.
        audit_dir: Directory where append-only audit JSONL files are written.
        trace_dir: Directory where full run traces are written as JSON.
        confidence_floor: Outputs below this confidence are routed to human review.
    """

    data_dir: Path
    audit_dir: Path
    trace_dir: Path = None  # type: ignore[assignment]  # see __post_init__
    confidence_floor: float = 0.70

    def __post_init__(self) -> None:
        # Provide a sensible default for trace_dir if not supplied.
        if self.trace_dir is None:
            object.__setattr__(self, "trace_dir", self.audit_dir.parent / "trace_logs")

    def deal_file(self, name: str) -> Path:
        """Resolve a sample-data file by name, raising if it is missing."""
        path = self.data_dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"Expected sample-data file not found: {path}. "
                f"Set SF_AGENTS_DATA_DIR or place the file under {self.data_dir}."
            )
        return path


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the process-wide :class:`Config`, resolved once and cached."""
    root = _repo_root()
    data_dir = Path(os.environ.get("SF_AGENTS_DATA_DIR", str(root / "Sample Data")))
    audit_dir = Path(os.environ.get("SF_AGENTS_AUDIT_DIR", str(root / "audit_logs")))
    trace_dir = Path(os.environ.get("SF_AGENTS_TRACE_DIR", str(root / "trace_logs")))
    floor = float(os.environ.get("SF_AGENTS_CONFIDENCE_FLOOR", "0.70"))
    return Config(data_dir=data_dir, audit_dir=audit_dir, trace_dir=trace_dir, confidence_floor=floor)
