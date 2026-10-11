"""Shared payment-evidence vocabulary.

The broad set covers every persisted monetary payment observation. The stricter
transition set contains only evidence types accepted by lifecycle payment gates.
"""

from __future__ import annotations

from typing import FrozenSet


# All known monetary payment observations, including legacy producer labels.
PAYMENT_EVIDENCE_TYPES: FrozenSet[str] = frozenset({
    "transaction_receipt",
    "platform_payment",
    "payment",
    "payout",
    "airdrop_payout",
    "refund",
    "payment_confirmation",
    "payment_gross",
    "balance_delta",
    "platform_transaction",
    "manual_attestation",
    "external_reconciliation",
})

# Evidence types that can satisfy a SUBMITTED->PAID transition. This remains
# narrower than the accounting vocabulary because legacy labels are not proof
# of an externally verified transition by themselves.
TRANSITION_PAYMENT_EVIDENCE_TYPES: FrozenSet[str] = frozenset({
    "payment_confirmation",
    "payment_gross",
    "balance_delta",
    "platform_transaction",
    "manual_attestation",
    "external_reconciliation",
})


__all__ = ["PAYMENT_EVIDENCE_TYPES", "TRANSITION_PAYMENT_EVIDENCE_TYPES"]