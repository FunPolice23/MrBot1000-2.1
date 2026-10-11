"""Tests for the shared payment-evidence vocabulary."""

import unittest

from agents.earning.economic_accounting import PAYMENT_EVIDENCE_TYPES
from agents.evidence.evidence_policy import REQUIREMENTS
from agents.earning.payment_evidence import TRANSITION_PAYMENT_EVIDENCE_TYPES


class TestPaymentEvidenceVocabulary(unittest.TestCase):
    def test_accounting_uses_shared_broad_vocabulary(self):
        payment_slot = set(REQUIREMENTS["SUBMITTED->PAID"].required_types[-1])
        self.assertTrue(payment_slot <= PAYMENT_EVIDENCE_TYPES)
        self.assertIn("transaction_receipt", PAYMENT_EVIDENCE_TYPES)
        self.assertIn("payment_gross", PAYMENT_EVIDENCE_TYPES)

    def test_transition_vocabulary_is_explicit_subset(self):
        self.assertTrue(TRANSITION_PAYMENT_EVIDENCE_TYPES <= PAYMENT_EVIDENCE_TYPES)
        self.assertEqual(
            set(REQUIREMENTS["SUBMITTED->PAID"].required_types[-1]),
            set(TRANSITION_PAYMENT_EVIDENCE_TYPES),
        )

    def test_legacy_payment_labels_remain_accounting_observations(self):
        self.assertTrue({
            "transaction_receipt", "platform_payment", "payment", "payout",
            "airdrop_payout", "refund",
        } <= PAYMENT_EVIDENCE_TYPES)


if __name__ == "__main__":
    unittest.main()