"""Source connectors: turn raw deal documents into page-/row-keyed chunks.

Connectors are pure, deterministic primitives (no LLM). Their payloads are the
canonical *source chunks* that the verifier later resolves citations against:

* PDF connectors yield ``pages`` -- a list of ``{"page": <1-based int>, "text": str}``.
* The loan-tape connector yields ``columns`` and ``rows`` (0-indexed).
"""

from .investor_report import InvestorReportConnector
from .loan_tape import LoanTapeConnector
from .prospectus import ProspectusConnector

__all__ = [
    "InvestorReportConnector",
    "LoanTapeConnector",
    "ProspectusConnector",
]
