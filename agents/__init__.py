"""Lazy public exports for the agents package.

Importing ``agents`` must not eagerly construct every optional worker or
provider. Direct submodule imports remain unchanged, while these historical
package-level names resolve only when requested.
"""

from importlib import import_module


_EXPORTS = {
    "AirdropScanner": ("earning.airdrop_scanner", "AirdropScanner"),
    "AirdropOpportunity": ("earning.airdrop_scanner", "AirdropOpportunity"),
    "WorkerAgent": ("brains.base_worker", "WorkerAgent"),
    "SharedContext": ("brains.shared_context", "SharedContext"),
    "SocialEarningPlatform": ("earning.social_earning_platform", "SocialEarningPlatform"),
    "FactLedger": ("cognition.fact_ledger", "FactLedger"),
    "Claim": ("cognition.fact_ledger", "Claim"),
    "ClaimStatus": ("cognition.fact_ledger", "ClaimStatus"),
    "SourceKind": ("cognition.fact_ledger", "SourceKind"),
    "LedgerEntry": ("cognition.fact_ledger", "LedgerEntry"),
    "OperatorOverrideRegistry": ("cognition.operator_override", "OperatorOverrideRegistry"),
    "OverrideRecord": ("cognition.operator_override", "OverrideRecord"),
    "EpistemicLevel": ("cognition.epistemic", "EpistemicLevel"),
    "classify": ("cognition.epistemic", "classify"),
    "confidence": ("cognition.epistemic", "confidence"),
    "disclaimer": ("cognition.epistemic", "disclaimer"),
    "context_note": ("cognition.epistemic", "context_note"),
    "extract_monetary_values": ("evidence.numeric_evidence", "extract_monetary_values"),
    "extract_monetary_spans": ("evidence.numeric_evidence", "extract_monetary_spans"),
    "unsupported_values": ("evidence.numeric_evidence", "unsupported_values"),
    "has_unsupported_values": ("evidence.numeric_evidence", "has_unsupported_values"),
    "DialogueHonestyService": ("cognition.dialogue_honesty", "DialogueHonestyService"),
}


def __getattr__(name):
    try:
        module_name, symbol = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), symbol)
    globals()[name] = value
    return value

__all__ = [
    'WorkerAgent',
    'SharedContext',
    'AirdropScanner',
    'AirdropOpportunity',
    'SocialEarningPlatform',
    # Honesty / epistemic stack (v2.1.1 experimental integration surface).
    'FactLedger',
    'Claim',
    'ClaimStatus',
    'SourceKind',
    'LedgerEntry',
    'OperatorOverrideRegistry',
    'OverrideRecord',
    'EpistemicLevel',
    'classify',
    'confidence',
    'disclaimer',
    'context_note',
    'extract_monetary_values',
    'extract_monetary_spans',
    'unsupported_values',
    'has_unsupported_values',
    'DialogueHonestyService',
]
