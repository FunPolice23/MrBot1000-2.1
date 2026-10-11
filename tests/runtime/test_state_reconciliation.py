"""Focused tests for read-only cross-store reconciliation."""

import unittest
from types import SimpleNamespace

from agents.evidence.evidence import EvidenceStatus, VerificationLevel
from agents.core.state_reconciliation import reconcile_opportunity


class TestStateReconciliation(unittest.TestCase):
    def test_paid_without_verified_payment_is_high_conflict(self):
        report = reconcile_opportunity(
            "opp-1",
            lifecycle=SimpleNamespace(get_state=lambda _: {"status": "paid"}),
            evidence_store=SimpleNamespace(for_subject=lambda *_: []),
        )
        conflicts = {conflict.category: conflict for conflict in report.conflicts}
        self.assertIn("lifecycle_evidence", conflicts)
        self.assertEqual(conflicts["lifecycle_evidence"].severity, "high")

    def test_verified_payment_without_paid_lifecycle_is_high_conflict(self):
        evidence = SimpleNamespace(
            evidence_type="payment_gross",
            status=EvidenceStatus.VERIFIED,
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
            amount=25.0,
            currency="usd",
        )
        report = reconcile_opportunity(
            "opp-1",
            lifecycle=SimpleNamespace(get_state=lambda _: {"status": "completed"}),
            evidence_store=SimpleNamespace(for_subject=lambda *_: [evidence]),
        )
        self.assertEqual(report.conflicts[0].category, "evidence_lifecycle")

    def test_currency_conversion_matches_accounting_revenue(self):
        evidence = [
            SimpleNamespace(
                evidence_type="payment_gross", status=EvidenceStatus.VERIFIED,
                verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
                amount=100.0, currency="usd",
            ),
            SimpleNamespace(
                evidence_type="external_reconciliation", status=EvidenceStatus.VERIFIED,
                verification_level=VerificationLevel.L4_INDEPENDENT_VERIFICATION,
                amount=1.0, currency="eth",
            ),
        ]
        report = reconcile_opportunity(
            "opp-1",
            lifecycle=SimpleNamespace(get_state=lambda _: {"status": "paid"}),
            evidence_store=SimpleNamespace(for_subject=lambda *_: evidence),
            accounting=SimpleNamespace(get_profile=lambda _: {"verified_revenue": 3600.0}),
        )
        self.assertNotIn("evidence_accounting", {c.category for c in report.conflicts})

    def test_failed_run_and_paid_lifecycle_are_conflicting(self):
        report = reconcile_opportunity(
            "opp-1",
            lifecycle=SimpleNamespace(get_state=lambda _: {"status": "paid"}),
            evidence_store=SimpleNamespace(for_subject=lambda *_: []),
            run_store=SimpleNamespace(list_runs=lambda **_: [{
                "opportunity_id": "opp-1", "status": "FAILED"
            }]),
        )
        categories = {conflict.category for conflict in report.conflicts}
        self.assertIn("run_lifecycle", categories)

    def test_clean_unpaid_state_has_no_conflicts(self):
        report = reconcile_opportunity(
            "opp-1",
            lifecycle=SimpleNamespace(get_state=lambda _: {"status": "completed"}),
            portfolio=SimpleNamespace(get=lambda _: {"work_status": "COMPLETED"}),
            evidence_store=SimpleNamespace(for_subject=lambda *_: []),
            accounting=SimpleNamespace(get_profile=lambda _: {"verified_revenue": 0.0}),
            run_store=SimpleNamespace(list_runs=lambda **_: []),
        )
        self.assertFalse(report.has_conflicts)


if __name__ == "__main__":
    unittest.main()