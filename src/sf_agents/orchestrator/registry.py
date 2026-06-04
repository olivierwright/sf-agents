"""The registry: the catalogue of primitives the planner may compose.

A registry maps a primitive's ``name`` to a *factory* -- a callable that builds a
fresh instance given an optional audit hook. Factories (rather than instances)
let the executor wire each primitive to the run's audit logger, and let callers
inject a mock LLM for offline testing.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..primitives.base import AuditHook, BasePrimitive

PrimitiveFactory = Callable[[Optional[AuditHook]], BasePrimitive]


class Registry:
    """A name-keyed catalogue of primitive factories with introspection."""

    def __init__(self) -> None:
        self._factories: dict[str, PrimitiveFactory] = {}
        self._descriptions: dict[str, dict[str, str]] = {}

    def register(self, factory: PrimitiveFactory) -> None:
        """Register a primitive factory.

        The factory is invoked once immediately (with no audit hook) to read the
        primitive's ``name``/``version``/``capability`` for the catalogue.

        Raises:
            ValueError: If a primitive with the same name is already registered.
        """
        probe = factory(None)
        name = probe.name
        if name in self._factories:
            raise ValueError(f"Primitive already registered: {name!r}")
        self._factories[name] = factory
        self._descriptions[name] = probe.describe()

    def build(self, name: str, audit_hook: Optional[AuditHook] = None) -> BasePrimitive:
        """Construct a fresh primitive instance wired to ``audit_hook``.

        Raises:
            KeyError: If ``name`` is not registered.
        """
        if name not in self._factories:
            raise KeyError(f"Unknown primitive: {name!r}")
        return self._factories[name](audit_hook)

    def names(self) -> list[str]:
        """Registered primitive names, sorted."""
        return sorted(self._factories)

    def describe(self) -> list[dict[str, str]]:
        """Planner-facing catalogue: ``[{name, version, capability}, ...]``."""
        return [self._descriptions[n] for n in self.names()]

    def __contains__(self, name: str) -> bool:
        return name in self._factories


def build_default_registry(llm: Optional[Callable] = None) -> Registry:
    """Build a registry containing every shipped primitive.

    Args:
        llm: Optional JSON-LLM callable injected into LLM-backed primitives
            (extractor, comparator). Defaults inside each primitive to the real
            Bedrock client; pass a mock here for offline use.

    Returns:
        A populated :class:`Registry`.
    """
    from ..primitives.analyzers.cashflow_anomaly import CashflowAnomalyAnalyzer
    from ..primitives.analyzers.claim_vs_collateral import ClaimVsCollateral
    from ..primitives.analyzers.consistency import ConsistencyAnalyzer
    from ..primitives.analyzers.covenant_compliance import CovenantComplianceAnalyzer
    from ..primitives.analyzers.definition_comparator import DefinitionComparator
    from ..primitives.analyzers.general_analyzer import GeneralAnalyzer
    from ..primitives.analyzers.rating_action import RatingActionAnalyzer
    from ..primitives.connectors.investor_report import InvestorReportConnector
    from ..primitives.connectors.loan_tape import LoanTapeConnector
    from ..primitives.connectors.pdf_document import PdfDocumentConnector
    from ..primitives.connectors.prospectus import ProspectusConnector
    from ..primitives.connectors.remittance_file import RemittanceFileConnector
    from ..primitives.connectors.text import TextConnector
    from ..primitives.extractors.covenants import CovenantExtractor
    from ..primitives.extractors.definition_extractor import DefinitionExtractor
    from ..primitives.extractors.general_extractor import GeneralExtractor
    from ..primitives.extractors.locator import LocatorExtractor
    from ..primitives.extractors.table_extractor import TableExtractor
    from ..primitives.extractors.waterfall import WaterfallExtractor
    from ..primitives.validators.esma_schema import EsmaSchemaValidator

    registry = Registry()
    # Connectors
    registry.register(lambda hook: ProspectusConnector(audit_hook=hook))
    registry.register(lambda hook: InvestorReportConnector(audit_hook=hook))
    registry.register(lambda hook: PdfDocumentConnector(audit_hook=hook))
    registry.register(lambda hook: LoanTapeConnector(audit_hook=hook))
    registry.register(lambda hook: RemittanceFileConnector(audit_hook=hook))
    registry.register(lambda hook: TextConnector(audit_hook=hook))
    # Validators
    registry.register(lambda hook: EsmaSchemaValidator(audit_hook=hook))
    # Extractors (domain-specific)
    registry.register(lambda hook: DefinitionExtractor(llm=llm, audit_hook=hook))
    registry.register(lambda hook: WaterfallExtractor(llm=llm, audit_hook=hook))
    registry.register(lambda hook: CovenantExtractor(llm=llm, audit_hook=hook))
    # Extractors (general-purpose)
    registry.register(lambda hook: LocatorExtractor(llm=llm, audit_hook=hook))
    registry.register(lambda hook: GeneralExtractor(llm=llm, audit_hook=hook))
    registry.register(lambda hook: TableExtractor(llm=llm, audit_hook=hook))
    # Analyzers (domain-specific)
    registry.register(lambda hook: DefinitionComparator(llm=llm, audit_hook=hook))
    registry.register(lambda hook: ClaimVsCollateral(llm=llm, audit_hook=hook))
    registry.register(lambda hook: CashflowAnomalyAnalyzer(llm=llm, audit_hook=hook))
    registry.register(lambda hook: CovenantComplianceAnalyzer(audit_hook=hook))
    registry.register(lambda hook: RatingActionAnalyzer(llm=llm, audit_hook=hook))
    # Analyzers (general-purpose)
    registry.register(lambda hook: GeneralAnalyzer(llm=llm, audit_hook=hook))
    registry.register(lambda hook: ConsistencyAnalyzer(llm=llm, audit_hook=hook))
    return registry
